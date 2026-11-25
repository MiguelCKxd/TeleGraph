@import AVKit;
@import AVFoundation;
@import CoreMedia;
@import CoreVideo;
@import UIKit;

@interface TGCallPiPVideo : UIView
@end

@implementation TGCallPiPVideo
+ (Class)layerClass { return AVSampleBufferDisplayLayer.class; }
@end

// iOS 15's video-call content source keeps playing independently of WKWebView.
@interface TGCallPiP : NSObject <AVPictureInPictureControllerDelegate>
@property(nonatomic, readonly) NSInteger state;
+ (BOOL)supported;
- (BOOL)openFrom:(UIView *)visibleView;
- (void)showBytes:(uintptr_t)address length:(NSUInteger)length;
- (void)clear;
- (void)close;
@end

@implementation TGCallPiP {
    AVPictureInPictureController *_controller;
    TGCallPiPVideo *_video;
    NSInteger _state;
}

+ (BOOL)supported { return [AVPictureInPictureController isPictureInPictureSupported]; }
- (NSInteger)state { return _state; }
- (BOOL)openFrom:(UIView *)visibleView {
    if (![TGCallPiP supported] || !visibleView.window || _controller) return NO;
    AVPictureInPictureVideoCallViewController *content = [AVPictureInPictureVideoCallViewController new];
    content.preferredContentSize = CGSizeMake(480, 270);
    _video = [[TGCallPiPVideo alloc] initWithFrame:content.view.bounds];
    _video.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    _video.backgroundColor = UIColor.blackColor;
    ((AVSampleBufferDisplayLayer *)_video.layer).videoGravity = AVLayerVideoGravityResizeAspect;
    [content.view addSubview:_video];
    AVPictureInPictureControllerContentSource *source = [[AVPictureInPictureControllerContentSource alloc]
        initWithActiveVideoCallSourceView:visibleView contentViewController:content];
    _controller = [[AVPictureInPictureController alloc] initWithContentSource:source];
    if (!_controller) return NO;
    _controller.delegate = self;
    _controller.canStartPictureInPictureAutomaticallyFromInline = NO;
    _state = 1;
    [self startWhenReady:40];
    return YES;
}

- (void)startWhenReady:(NSUInteger)remaining {
    if (_state != 1) return;
    if (_controller.pictureInPicturePossible) {
        [_controller startPictureInPicture];
    } else if (remaining) {
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 50 * NSEC_PER_MSEC), dispatch_get_main_queue(), ^{
            [self startWhenReady:remaining - 1];
        });
    } else [self close];
}

- (void)showBytes:(uintptr_t)address length:(NSUInteger)length {
    if (!_state || !address || !length) return;
    NSData *data = [NSData dataWithBytesNoCopy:(void *)address length:length freeWhenDone:NO];
    __attribute__((objc_precise_lifetime)) UIImage *decoded = [UIImage imageWithData:data];
    CGImageRef image = decoded.CGImage;
    if (!image) return;
    size_t width = CGImageGetWidth(image), height = CGImageGetHeight(image);
    CVPixelBufferRef pixels = NULL;
    NSDictionary *options = @{(id)kCVPixelBufferIOSurfacePropertiesKey: @{}};
    if (CVPixelBufferCreate(NULL, width, height, kCVPixelFormatType_32BGRA,
                            (__bridge CFDictionaryRef)options, &pixels) != kCVReturnSuccess) return;
    CVPixelBufferLockBaseAddress(pixels, 0);
    CGColorSpaceRef color = CGColorSpaceCreateDeviceRGB();
    CGContextRef context = CGBitmapContextCreate(CVPixelBufferGetBaseAddress(pixels), width, height, 8,
        CVPixelBufferGetBytesPerRow(pixels), color, kCGBitmapByteOrder32Little | kCGImageAlphaPremultipliedFirst);
    if (context) {
        CGContextDrawImage(context, CGRectMake(0, 0, width, height), image);
        CGContextRelease(context);
    }
    CGColorSpaceRelease(color);
    CVPixelBufferUnlockBaseAddress(pixels, 0);
    CMVideoFormatDescriptionRef format = NULL;
    CMSampleBufferRef sample = NULL;
    CMSampleTimingInfo timing = {kCMTimeInvalid, CMClockGetTime(CMClockGetHostTimeClock()), kCMTimeInvalid};
    if (context && CMVideoFormatDescriptionCreateForImageBuffer(NULL, pixels, &format) == noErr &&
        CMSampleBufferCreateReadyWithImageBuffer(NULL, pixels, format, &timing, &sample) == noErr) {
        CFArrayRef list = CMSampleBufferGetSampleAttachmentsArray(sample, YES);
        CFDictionarySetValue((CFMutableDictionaryRef)CFArrayGetValueAtIndex(list, 0),
                             kCMSampleAttachmentKey_DisplayImmediately, kCFBooleanTrue);
        AVSampleBufferDisplayLayer *layer = (AVSampleBufferDisplayLayer *)_video.layer;
        if (layer.status == AVQueuedSampleBufferRenderingStatusFailed) [layer flush];
        if (layer.readyForMoreMediaData) [layer enqueueSampleBuffer:sample];
        CFRelease(sample);
    }
    if (format) CFRelease(format);
    CVPixelBufferRelease(pixels);
}

- (void)clear { [(AVSampleBufferDisplayLayer *)_video.layer flushAndRemoveImage]; }
- (void)close {
    _state = 0;
    [self clear];
    _controller.delegate = nil;
    [_controller stopPictureInPicture];
    _controller.contentSource = nil;
    _controller = nil;
    _video = nil;
}
- (void)pictureInPictureControllerDidStartPictureInPicture:(AVPictureInPictureController *)controller { _state = 2; }
- (void)pictureInPictureControllerDidStopPictureInPicture:(AVPictureInPictureController *)controller { [self close]; }
- (void)pictureInPictureController:(AVPictureInPictureController *)controller failedToStartPictureInPictureWithError:(NSError *)error { [self close]; }
- (void)pictureInPictureController:(AVPictureInPictureController *)controller
        restoreUserInterfaceForPictureInPictureStopWithCompletionHandler:(void (^)(BOOL))completion { completion(YES); }
@end
