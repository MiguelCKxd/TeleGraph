#import <AVFoundation/AVFoundation.h>
#import <os/lock.h>
#import <stdatomic.h>
#import <stdint.h>

typedef struct {
    int64_t timestamp;
    int rotation;
    uint16_t width, height;
} TGCallFrameData;
typedef int (*TGSendCallFrame)(void *, int64_t, int, const unsigned char *, size_t, TGCallFrameData);

// One instance per Telegram call. Only the input worker enters NTgCalls.
@interface TGCallAudio : NSObject
@property(nonatomic, readonly) NSInteger errorCode;
- (BOOL)startWithHandle:(uint64_t)handle peer:(int64_t)peer sender:(uintptr_t)sender;
- (void)appendBytes:(uintptr_t)address length:(NSUInteger)length;
- (void)stop;
@end

@implementation TGCallAudio {
    AVAudioEngine *_engine;
    AVAudioConverter *_converter;
    AVAudioFormat *_pcm;
    dispatch_queue_t _capture, _control;
    id _configurationObserver, _interruptionObserver;
    BOOL _interrupted, _tapInstalled;
    NSMutableData *_pending;
    TGSendCallFrame _send;
    uint64_t _handle;
    int64_t _peer, _timestamp;
    atomic_uint _work;
    atomic_bool _running;
    os_unfair_lock _lock;
    int16_t _ring[12000];
    NSUInteger _head, _count;
    NSInteger _errorCode;
}

- (instancetype)init {
    if ((self = [super init])) {
        _lock = OS_UNFAIR_LOCK_INIT;
        _control = dispatch_queue_create("org.tgas.call.audio-state", DISPATCH_QUEUE_SERIAL);
        _capture = dispatch_queue_create("org.tgas.call.input", DISPATCH_QUEUE_SERIAL);
        _pcm = [[AVAudioFormat alloc] initWithCommonFormat:AVAudioPCMFormatInt16
                                              sampleRate:48000 channels:1 interleaved:YES];
        _pending = [NSMutableData data];
    }
    return self;
}

- (void)appendBytes:(uintptr_t)address length:(NSUInteger)length {
    if (!atomic_load(&_running) || !address || length % 2) return;
    const int16_t *data = (const int16_t *)address;
    NSUInteger left = length / sizeof(int16_t), capacity = sizeof(_ring) / sizeof(_ring[0]);
    if (left > capacity) { data += left - capacity; left = capacity; }
    os_unfair_lock_lock(&_lock);
    NSUInteger drop = _count + left > capacity ? _count + left - capacity : 0;
    _head = (_head + drop) % capacity;
    _count -= drop;
    NSUInteger tail = (_head + _count) % capacity, first = MIN(left, capacity - tail);
    memcpy(_ring + tail, data, first * sizeof(int16_t));
    memcpy(_ring, data + first, (left - first) * sizeof(int16_t));
    _count += left;
    os_unfair_lock_unlock(&_lock);
}

- (void)render:(AudioBufferList *)list frames:(AVAudioFrameCount)frames {
    for (UInt32 i = 0; i < list->mNumberBuffers; i++)
        memset(list->mBuffers[i].mData, 0, list->mBuffers[i].mDataByteSize);
    if (!list->mNumberBuffers || !os_unfair_lock_trylock(&_lock)) return;
    float *samples = list->mBuffers[0].mData;
    NSUInteger n = MIN(MIN(frames, list->mBuffers[0].mDataByteSize / sizeof(float)), _count);
    for (NSUInteger i = 0; i < n; i++) {
        samples[i] = _ring[_head] / 32768.f;
        _head = (_head + 1) % (sizeof(_ring) / sizeof(_ring[0]));
    }
    _count -= n;
    os_unfair_lock_unlock(&_lock);
}

- (void)convertAndSend:(AVAudioPCMBuffer *)input {
    if (!atomic_load(&_running)) return;
    if (!_converter || ![_converter.inputFormat isEqual:input.format]) {
        _converter = [[AVAudioConverter alloc] initFromFormat:input.format toFormat:_pcm];
        _converter.primeMethod = AVAudioConverterPrimeMethod_None;
    }
    if (!_converter || input.format.sampleRate <= 0) return;
    AVAudioFrameCount capacity = (AVAudioFrameCount)ceil(input.frameLength * 48000. / input.format.sampleRate) + 64;
    AVAudioPCMBuffer *output = [[AVAudioPCMBuffer alloc] initWithPCMFormat:_pcm frameCapacity:capacity];
    __block BOOL supplied = NO;
    NSError *error = nil;
    AVAudioConverterOutputStatus result = [_converter convertToBuffer:output error:&error
        withInputFromBlock:^AVAudioBuffer *(AVAudioPacketCount requested, AVAudioConverterInputStatus *status) {
            if (supplied) { *status = AVAudioConverterInputStatus_NoDataNow; return nil; }
            supplied = YES; *status = AVAudioConverterInputStatus_HaveData; return input;
        }];
    if (result == AVAudioConverterOutputStatus_Error || !output.frameLength) return;
    [_pending appendBytes:output.audioBufferList->mBuffers[0].mData length:output.frameLength * 2];
    NSUInteger sent = 0;
    const NSUInteger bytesPerTenMs = 480 * sizeof(int16_t);
    const uint8_t *bytes = _pending.bytes;
    int64_t now = (int64_t)(NSDate.date.timeIntervalSince1970 * 1000.);
    if (_timestamp < now-200) _timestamp = now - (int64_t)(_pending.length / 96);
    while (_pending.length - sent >= bytesPerTenMs) {
        TGCallFrameData frame = {_timestamp, 0, 0, 0};
        _send((void *)(uintptr_t)_handle, _peer, 0, bytes + sent, bytesPerTenMs, frame);
        _timestamp += 10;
        sent += bytesPerTenMs;
    }
    if (sent) [_pending replaceBytesInRange:NSMakeRange(0, sent) withBytes:NULL length:0];
}

- (void)consume:(AVAudioPCMBuffer *)buffer {
    if (!atomic_load(&_running)) return;
    if (atomic_fetch_add(&_work,1) >= 3) { atomic_fetch_sub(&_work,1); return; }
    AVAudioPCMBuffer *copy = [[AVAudioPCMBuffer alloc] initWithPCMFormat:buffer.format frameCapacity:buffer.frameLength];
    copy.frameLength = buffer.frameLength;
    for (UInt32 i = 0; i < buffer.audioBufferList->mNumberBuffers; i++) {
        const AudioBuffer *source = &buffer.audioBufferList->mBuffers[i];
        AudioBuffer *destination = &copy.mutableAudioBufferList->mBuffers[i];
        memcpy(destination->mData, source->mData, MIN(source->mDataByteSize, destination->mDataByteSize));
    }
    dispatch_async(_capture, ^{
        @autoreleasepool { [self convertAndSend:copy]; }
        atomic_fetch_sub(&self->_work,1);
    });
}

- (BOOL)startWithHandle:(uint64_t)handle peer:(int64_t)peer sender:(uintptr_t)sender {
    __block BOOL result = NO;
    dispatch_sync(_control, ^{
        @try {
            result = [self startEngineWithHandle:handle peer:peer sender:sender];
        } @catch (NSException *exception) {
            // A route can disappear between inspecting the format and installing the tap.
            self->_errorCode = -2;
            [self stopEngine];
        }
    });
    return result;
}

- (void)resumeEngine:(AVAudioEngine *)engine {
    if (!atomic_load(&_running) || _engine != engine || _interrupted || engine.running) return;
    NSError *error = nil;
    if (![engine startAndReturnError:&error]) _errorCode = error.code;
}

- (BOOL)startEngineWithHandle:(uint64_t)handle peer:(int64_t)peer sender:(uintptr_t)sender {
    if (atomic_load(&_running)) {
        [self resumeEngine:_engine];
        return _engine.running || _interrupted;
    }
    _send = (TGSendCallFrame)sender;
    if (!_send) return NO;
    _handle = handle; _peer = peer; _errorCode = 0;
    AVAudioEngine *engine = [[AVAudioEngine alloc] init];
    AVAudioInputNode *input = engine.inputNode;
    AVAudioFormat *format = [input outputFormatForBus:0];
    if (!format.channelCount || !format.sampleRate) { _errorCode = -1; return NO; }
    AVAudioFormat *mono = [[AVAudioFormat alloc] initStandardFormatWithSampleRate:48000 channels:1];
    __weak TGCallAudio *weakSelf = self;
    AVAudioSourceNode *output = [[AVAudioSourceNode alloc] initWithFormat:mono
        renderBlock:^OSStatus(BOOL *silence, const AudioTimeStamp *time, AVAudioFrameCount frames, AudioBufferList *list) {
            [weakSelf render:list frames:frames]; return noErr;
        }];
    _engine = engine;
    [engine attachNode:output];
    [engine connect:output to:engine.mainMixerNode format:mono];
    [input installTapOnBus:0 bufferSize:960 format:nil block:^(AVAudioPCMBuffer *buffer, AVAudioTime *time) {
        [weakSelf consume:buffer];
    }];
    _tapInstalled = YES;
    _interrupted = NO;
    NSNotificationCenter *notifications = NSNotificationCenter.defaultCenter;
    __weak AVAudioEngine *observedEngine = engine;
    _configurationObserver = [notifications addObserverForName:AVAudioEngineConfigurationChangeNotification
        object:engine queue:nil usingBlock:^(NSNotification *notification) {
            // iOS stops the graph after its hardware sample rate or channel count changes.
            // Resume off the engine's own notification queue.
            TGCallAudio *audio = weakSelf;
            if (audio) dispatch_async(audio->_control, ^{ [audio resumeEngine:observedEngine]; });
        }];
    _interruptionObserver = [notifications addObserverForName:AVAudioSessionInterruptionNotification
        object:AVAudioSession.sharedInstance queue:nil usingBlock:^(NSNotification *notification) {
            TGCallAudio *audio = weakSelf;
            NSDictionary *info = notification.userInfo;
            if (audio) dispatch_async(audio->_control, ^{
                if (audio->_engine != observedEngine || !atomic_load(&audio->_running)) return;
                AVAudioSessionInterruptionType type = [info[AVAudioSessionInterruptionTypeKey] unsignedIntegerValue];
                audio->_interrupted = type == AVAudioSessionInterruptionTypeBegan;
                if (!audio->_interrupted && ([info[AVAudioSessionInterruptionOptionKey] unsignedIntegerValue]
                                             & AVAudioSessionInterruptionOptionShouldResume)) {
                    [audio resumeEngine:observedEngine];
                }
            });
        }];
    atomic_store(&_running,true);
    NSError *error = nil;
    if (![engine startAndReturnError:&error]) {
        _errorCode = error.code; [self stopEngine]; return NO;
    }
    return YES;
}

- (void)stop {
    dispatch_sync(_control, ^{ [self stopEngine]; });
}

- (void)stopEngine {
    atomic_store(&_running, false);
    NSNotificationCenter *notifications = NSNotificationCenter.defaultCenter;
    if (_configurationObserver) [notifications removeObserver:_configurationObserver];
    if (_interruptionObserver) [notifications removeObserver:_interruptionObserver];
    _configurationObserver = nil;
    _interruptionObserver = nil;
    [_engine stop];
    if (_tapInstalled) [_engine.inputNode removeTapOnBus:0];
    _tapInstalled = NO;
    _engine = nil;
    dispatch_sync(_capture, ^{});
    _converter = nil; [_pending setLength:0]; _timestamp=0;
    os_unfair_lock_lock(&_lock); _head=0; _count=0; os_unfair_lock_unlock(&_lock);
}
@end
