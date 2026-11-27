#import <UserNotifications/UserNotifications.h>
#import <Intents/Intents.h>
#import "TGNotificationPresentation.m"

@interface TeleGraphNotificationService : UNNotificationServiceExtension
@property(copy) void (^pendingHandler)(UNNotificationContent *);
@property(strong) UNNotificationContent *pendingContent;
@end

@implementation TeleGraphNotificationService

// Accept only integral Telegram IDs. They are also used as local filenames.
static NSNumber *positiveID(id value) {
    if (![value isKindOfClass:NSNumber.class] && ![value isKindOfClass:NSString.class]) return nil;
    NSString *text = [value description];
    long long number = text.longLongValue;
    return number > 0 && number < (1LL << 53) && [text isEqualToString:[@(number) stringValue]] ? @(number) : nil;
}

- (void)didReceiveNotificationRequest:(UNNotificationRequest *)request
                  withContentHandler:(void (^)(UNNotificationContent *))handler {
    UNMutableNotificationContent *content = [request.content mutableCopy];
    UNMutableNotificationContent *generic = [content mutableCopy];
    generic.title = @"TeleGraph"; generic.subtitle = @"";
    generic.body = NSLocalizedString(@"New message", nil);
    generic.categoryIdentifier = @"";
    self.pendingContent = generic;
    self.pendingHandler = handler;
    // Only this extension may designate a preview as a CarPlay message.
    if ([content.categoryIdentifier isEqualToString:@"TeleGraphMessage"]) content.categoryIdentifier = @"";
    NSDictionary *payload = content.userInfo;
    NSDictionary *custom = payload[@"custom"];
    NSDictionary *aps = payload[@"aps"];
    NSDictionary *alert = [aps isKindOfClass:NSDictionary.class] ? aps[@"alert"] : nil;
    if (![custom isKindOfClass:NSDictionary.class] || !positiveID(custom[@"msg_id"])) {
        [self finish:content];
        return;
    }
    NSURL *root = [self previewRoot];
    NSDictionary *policy = root ? [NSDictionary dictionaryWithContentsOfURL:[root URLByAppendingPathComponent:@"policy.plist"]] : nil;
    NSNumber *account = positiveID(payload[@"user_id"]);
    NSArray *allowed = [policy[@"accounts"] isKindOfClass:NSArray.class] ? policy[@"accounts"] : nil;
    if (!account || ![allowed containsObject:account]) {
        content.title = @"TeleGraph";
        content.subtitle = @"";
        content.body = policy[@"generic"] ?: NSLocalizedString(@"New message", nil);
        [self finish:content];
        return;
    }
    NSString *key = [alert isKindOfClass:NSDictionary.class] ? alert[@"loc-key"] : nil;
    if (![key isKindOfClass:NSString.class]) key = payload[@"loc_key"];
    if (![key isKindOfClass:NSString.class]) key = @"";
    if ([key containsString:@"NOTEXT"] || [key containsString:@"NO_TEXT"] ||
        [key hasPrefix:@"ENCRYPTED"] || [key containsString:@"HIDDEN"]) {
        [self finish:content];
        return;
    }
    // A group/chat identifier is distinct from the sender of a group message.
    NSNumber *channel = positiveID(custom[@"channel_id"]);
    NSNumber *chat = positiveID(custom[@"chat_id"]);
    NSNumber *senderChannel = positiveID(custom[@"chat_from_broadcast_id"]) ?: positiveID(custom[@"chat_from_group_id"]);
    NSNumber *sender = senderChannel ? @(-1000000000000LL - senderChannel.longLongValue)
        : positiveID(custom[@"chat_from_id"]) ?: positiveID(custom[@"from_id"]);
    if (!sender && channel) sender = @(-1000000000000LL - channel.longLongValue);
    if (!sender) { [self finish:content]; return; }
    NSNumber *peer = channel ? @(-1000000000000LL - channel.longLongValue) : chat ? @(-chat.longLongValue) : sender;
    NSString *name = content.title;
    NSArray *arguments = [alert isKindOfClass:NSDictionary.class] ? alert[@"loc-args"] : nil;
    if (![arguments isKindOfClass:NSArray.class]) arguments = payload[@"loc_args"];
    BOOL messageKey = [key hasPrefix:@"MESSAGE_"] || [key hasPrefix:@"CHAT_MESSAGE_"] || [key hasPrefix:@"CHANNEL_MESSAGE_"];
    if (messageKey && [arguments isKindOfClass:NSArray.class] && [arguments.firstObject isKindOfClass:NSString.class]) {
        name = arguments.firstObject;
    }
    if (!name.length) { [self finish:content]; return; }
    NSURL *folder = [root URLByAppendingPathComponent:account.stringValue isDirectory:YES];
    NSURL *photo = [folder URLByAppendingPathComponent:[sender.stringValue stringByAppendingPathExtension:@"jpg"]];
    NSDate *modified = nil;
    NSNumber *size = nil;
    [photo getResourceValue:&modified forKey:NSURLContentModificationDateKey error:nil];
    [photo getResourceValue:&size forKey:NSURLFileSizeKey error:nil];
    NSTimeInterval age = modified ? -modified.timeIntervalSinceNow : -1;
    NSData *bytes = age >= 0 && age < 3 * 86400 && size.unsignedLongLongValue <= 512 * 1024
        ? [NSData dataWithContentsOfURL:photo] : nil;
    NSString *thread = [NSString stringWithFormat:@"%@:%@", account, peer];
    if (messageKey && [arguments isKindOfClass:NSArray.class] && [arguments.firstObject isKindOfClass:NSString.class] &&
        [NSBundle.mainBundle.infoDictionary[@"TeleGraphCarPlayEnabled"] boolValue]) {
        NSMutableDictionary *info = [content.userInfo mutableCopy];
        info[@"TeleGraphMessageRoute"] = @[account, peer, positiveID(custom[@"msg_id"])];
        content.userInfo = info;
        content.categoryIdentifier = @"TeleGraphMessage";
    }
    content.title = name;
    content.threadIdentifier = thread;
    // No network fetch and no asynchronous donation gate: a missing/corrupt avatar
    // may change presentation, never the delivery of a real message.
    [self finish:[TGNotificationPresentation decorateContent:content account:account.stringValue peer:peer.stringValue
        sender:sender.stringValue photo:bytes conversation:nil]];
}

- (NSURL *)previewRoot {
    NSString *bundle = NSBundle.mainBundle.bundleIdentifier.stringByDeletingPathExtension;
    NSString *group = [NSString stringWithFormat:@"group.%@", bundle];
    return [[NSFileManager.defaultManager containerURLForSecurityApplicationGroupIdentifier:group]
        URLByAppendingPathComponent:@"NoticePreviews" isDirectory:YES];
}

- (void)finish:(UNNotificationContent *)content {
    void (^handler)(UNNotificationContent *);
    @synchronized (self) {
        handler = self.pendingHandler;
        self.pendingHandler = nil;
        self.pendingContent = nil;
    }
    if (handler) handler(content);
}

- (void)serviceExtensionTimeWillExpire {
    UNNotificationContent *content;
    @synchronized (self) { content = self.pendingContent; }
    if (content) [self finish:content];
}
@end
