// The Network.framework application service is scoped to our iPhone and tvOS apps.
@import Network;
@import UIKit;

@interface TGTVLink : NSObject
+ (void)start;
+ (void)disconnect;
+ (NSString *)connectionID;
+ (NSString *)transportStatus;
+ (BOOL)share:(NSString *)json connection:(NSString *)identifier;
@end
@implementation TGTVLink
static nw_listener_t listener;
static nw_connection_t current;
static nw_connection_t pending;
static NSUInteger listenerGeneration;
static unsigned int retryDelay = 1;
static NSString *listenerStatus = @"idle";
static NSString *linkStatus = @"idle";
static NSString *connectionID;

+ (void)onMain:(dispatch_block_t)action {
    if (NSThread.isMainThread) action();
    else dispatch_sync(dispatch_get_main_queue(), action);
}
// These diagnostics carry only Network.framework states and error codes.
+ (void)record:(NSString *)area state:(int)state error:(nw_error_t)error {
    NSString *value = [NSString stringWithFormat:@"%d/%d/%d", state,
                       error ? nw_error_get_error_domain(error) : 0, error ? nw_error_get_error_code(error) : 0];
    if ([area isEqualToString:@"listener"]) listenerStatus = value;
    else linkStatus = value;
    NSLog(@"TeleGraph TV %@ state/domain/error %@", area, value);
}
+ (NSString *)transportStatus {
    __block NSString *value;
    [self onMain:^{ value = [NSString stringWithFormat:@"listener=%@ link=%@", listenerStatus, linkStatus]; }];
    return value;
}
+ (void)disconnect {
    [self onMain:^{
        if (pending) nw_connection_cancel(pending);
        if (current) nw_connection_cancel(current);
        pending = nil;
        current = nil;
        connectionID = nil;
        linkStatus = @"idle";
    }];
}
+ (void)stopAdvertising {
    ++listenerGeneration;
    if (listener) nw_listener_cancel(listener);
    listener = nil;
    listenerStatus = @"idle";
    retryDelay = 1;
    [self disconnect];
}
+ (void)start {
    if (@available(iOS 16.0, *)) {
        [self onMain:^{
            static dispatch_once_t once;
            dispatch_once(&once, ^{
                NSNotificationCenter *center = NSNotificationCenter.defaultCenter;
                for (NSString *name in @[UIApplicationDidEnterBackgroundNotification, UIApplicationProtectedDataWillBecomeUnavailable]) {
                    [center addObserverForName:name object:nil queue:NSOperationQueue.mainQueue
                                   usingBlock:^(NSNotification *note) { [self stopAdvertising]; }];
                }
                for (NSString *name in @[UIApplicationDidBecomeActiveNotification, UIApplicationProtectedDataDidBecomeAvailable]) {
                    [center addObserverForName:name object:nil queue:NSOperationQueue.mainQueue
                                   usingBlock:^(NSNotification *note) { [self start]; }];
                }
            });
            UIApplication *application = UIApplication.sharedApplication;
            if (listener || !application.protectedDataAvailable || application.applicationState != UIApplicationStateActive) return;
            NSUInteger generation = ++listenerGeneration;
            listener = nw_listener_create(nw_parameters_create_application_service());
            if (!listener) { listenerStatus = @"creation failed"; return; }
            nw_listener_set_queue(listener, dispatch_get_main_queue());
            nw_listener_set_advertise_descriptor(listener, nw_advertise_descriptor_create_application_service("telegraph-companion"));
            nw_listener_set_state_changed_handler(listener, ^(nw_listener_state_t state, nw_error_t error) {
                if (listenerGeneration != generation) return;
                [self record:@"listener" state:state error:error];
                if (state == nw_listener_state_ready) retryDelay = 1;
                if (state == nw_listener_state_failed || state == nw_listener_state_cancelled) {
                    if (state == nw_listener_state_failed) nw_listener_cancel(listener);
                    listener = nil;
                    NSUInteger retryGeneration = ++listenerGeneration;
                    unsigned int delay = retryDelay;
                    retryDelay = MIN(30U, 2 * delay);
                    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, delay * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
                        if (retryGeneration == listenerGeneration) [self start];
                    });
                }
            });
            nw_listener_set_new_connection_handler(listener, ^(nw_connection_t link) {
                if (generation != listenerGeneration) { nw_connection_cancel(link); return; }
                if (pending) nw_connection_cancel(pending);
                pending = link;
                nw_connection_set_queue(link, dispatch_get_main_queue());
                nw_connection_set_state_changed_handler(link, ^(nw_connection_state_t state, nw_error_t error) {
                    if (link != pending && link != current) return;
                    [self record:@"link" state:state error:error];
                    if (state == nw_connection_state_ready && link == pending) {
                        if (current) nw_connection_cancel(current);
                        pending = nil;
                        current = link;
                        connectionID = NSUUID.UUID.UUIDString;
                        nw_connection_receive(link, 1, 1, ^(dispatch_data_t data, nw_content_context_t context, bool end, nw_error_t err) {
                            if (link == current) {
                                nw_connection_cancel(link);
                                current = nil;
                                connectionID = nil;
                            }
                        });
                    } else if (state == nw_connection_state_failed || state == nw_connection_state_cancelled ||
                               (state == nw_connection_state_waiting && link == current)) {
                        if (link == pending) pending = nil;
                        if (link == current) { current = nil; connectionID = nil; }
                        nw_connection_cancel(link);
                    }
                });
                nw_connection_start(link);
            });
            nw_listener_start(listener);
        }];
    }
}
+ (NSString *)connectionID {
    __block NSString *result;
    [self onMain:^{ result = connectionID; }];
    return result;
}
+ (BOOL)share:(NSString *)json connection:(NSString *)identifier {
    NSData *body = [json dataUsingEncoding:NSUTF8StringEncoding];
    if (!body.length || body.length > 262144) return NO;
    __block BOOL accepted = NO;
    [self onMain:^{
        if (![connectionID isEqualToString:identifier] || !current ||
            !UIApplication.sharedApplication.protectedDataAvailable ||
            UIApplication.sharedApplication.applicationState != UIApplicationStateActive) return;
        uint32_t size = htonl((uint32_t)body.length);
        NSMutableData *frame = [NSMutableData dataWithBytes:&size length:4];
        [frame appendData:body];
        nw_connection_t link = current;
        dispatch_data_t bytes = dispatch_data_create(frame.bytes, frame.length, dispatch_get_main_queue(), ^{ (void)frame; });
        nw_connection_send(link, bytes, NW_CONNECTION_DEFAULT_MESSAGE_CONTEXT, true, ^(nw_error_t error) {
            if (error && current == link) {
                [self record:@"send" state:nw_connection_state_failed error:error];
                nw_connection_cancel(link);
                current = nil;
                connectionID = nil;
            }
        });
        accepted = YES;
    }];
    return accepted;
}
@end
