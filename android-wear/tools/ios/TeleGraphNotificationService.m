#import <UserNotifications/UserNotifications.h>
#import <Intents/Intents.h>

@interface TeleGraphNotificationService : UNNotificationServiceExtension
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
    // Only this extension may designate a preview as a CarPlay message.
    if ([content.categoryIdentifier isEqualToString:@"TeleGraphMessage"]) content.categoryIdentifier = @"";
    NSDictionary *payload = content.userInfo;
    NSDictionary *custom = payload[@"custom"];
    NSDictionary *aps = payload[@"aps"];
    NSDictionary *alert = [aps isKindOfClass:NSDictionary.class] ? aps[@"alert"] : nil;
    if (![custom isKindOfClass:NSDictionary.class] || !positiveID(custom[@"msg_id"])) {
        handler(content);
        return;
    }
    NSString *bundle = NSBundle.mainBundle.bundleIdentifier.stringByDeletingPathExtension;
    NSString *group = [NSString stringWithFormat:@"group.%@", bundle];
    NSURL *root = [[NSFileManager.defaultManager containerURLForSecurityApplicationGroupIdentifier:group]
                   URLByAppendingPathComponent:@"NoticePreviews" isDirectory:YES];
    NSDictionary *policy = root ? [NSDictionary dictionaryWithContentsOfURL:[root URLByAppendingPathComponent:@"policy.plist"]] : nil;
    NSNumber *account = positiveID(payload[@"user_id"]);
    if (!account || ![policy[@"accounts"] containsObject:account]) {
        content.title = @"TeleGraph";
        content.subtitle = @"";
        content.body = policy[@"generic"] ?: NSLocalizedString(@"New message", nil);
        handler(content);
        return;
    }
    NSString *key = [alert isKindOfClass:NSDictionary.class] ? alert[@"loc-key"] : nil;
    if (![key isKindOfClass:NSString.class]) key = payload[@"loc_key"];
    if (![key isKindOfClass:NSString.class]) key = @"";
    if ([key containsString:@"NOTEXT"] || [key containsString:@"NO_TEXT"] ||
        [key hasPrefix:@"ENCRYPTED"] || [key containsString:@"HIDDEN"]) {
        handler(content);
        return;
    }
    // A group/chat identifier is distinct from the sender of a group message.
    NSNumber *channel = positiveID(custom[@"channel_id"]);
    NSNumber *chat = positiveID(custom[@"chat_id"]);
    NSNumber *sender = positiveID(custom[@"chat_from_id"]) ?: positiveID(custom[@"from_id"]);
    if (!sender && channel) sender = @(-1000000000000LL - channel.longLongValue);
    if (!sender) { handler(content); return; }
    NSNumber *peer = channel ? @(-1000000000000LL - channel.longLongValue) : chat ? @(-chat.longLongValue) : sender;
    NSString *name = content.title;
    NSArray *arguments = [alert isKindOfClass:NSDictionary.class] ? alert[@"loc-args"] : nil;
    if (![arguments isKindOfClass:NSArray.class]) arguments = payload[@"loc_args"];
    BOOL messageKey = [key hasPrefix:@"MESSAGE_"] || [key hasPrefix:@"CHAT_MESSAGE_"] || [key hasPrefix:@"CHANNEL_MESSAGE_"];
    if (messageKey && [arguments isKindOfClass:NSArray.class] && [arguments.firstObject isKindOfClass:NSString.class]) {
        name = arguments.firstObject;
    }
    if (!name.length) { handler(content); return; }
    NSURL *folder = [root URLByAppendingPathComponent:account.stringValue isDirectory:YES];
    NSURL *photo = [folder URLByAppendingPathComponent:[sender.stringValue stringByAppendingPathExtension:@"jpg"]];
    NSDate *modified = nil;
    [photo getResourceValue:&modified forKey:NSURLContentModificationDateKey error:nil];
    NSData *bytes = modified && -modified.timeIntervalSinceNow < 3 * 86400 ? [NSData dataWithContentsOfURL:photo] : nil;
    INImage *image = bytes.length ? [INImage imageWithImageData:bytes] : nil;
    NSString *identity = [NSString stringWithFormat:@"%@:%@", account, sender];
    NSString *thread = [NSString stringWithFormat:@"%@:%@", account, peer];
    INPersonHandle *handle = [[INPersonHandle alloc] initWithValue:identity type:INPersonHandleTypeUnknown];
    INPerson *person = [[INPerson alloc] initWithPersonHandle:handle nameComponents:nil displayName:name image:image contactIdentifier:nil customIdentifier:identity];
    INSendMessageIntent *intent = [[INSendMessageIntent alloc] initWithRecipients:nil outgoingMessageType:INOutgoingMessageTypeOutgoingMessageText content:nil speakableGroupName:nil conversationIdentifier:thread serviceName:@"TeleGraph" sender:person attachments:nil];
    if (messageKey && [arguments isKindOfClass:NSArray.class] && [arguments.firstObject isKindOfClass:NSString.class] &&
        [NSBundle.mainBundle.infoDictionary[@"TeleGraphCarPlayEnabled"] boolValue]) {
        NSMutableDictionary *info = [content.userInfo mutableCopy];
        info[@"TeleGraphMessageRoute"] = @[account, peer, positiveID(custom[@"msg_id"])];
        content.userInfo = info;
        content.categoryIdentifier = @"TeleGraphMessage";
    }
    content.title = name;
    content.threadIdentifier = thread;
    INInteraction *interaction = [[INInteraction alloc] initWithIntent:intent response:nil];
    interaction.direction = INInteractionDirectionIncoming;
    [interaction donateInteractionWithCompletion:nil];
    handler([content contentByUpdatingWithProvider:intent error:nil] ?: content);
}
@end
