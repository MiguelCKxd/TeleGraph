// Run as an isolated iOS Simulator executable; no registration, delivery, account or network.
#import "../tools/ios/TeleGraphNotificationService.m"
#import <objc/runtime.h>

#define CHECK(condition) do { if (!(condition)) { fprintf(stderr, "FAIL line %d\n", __LINE__); exit(1); } } while (0)
static NSURL *testRoot;
static BOOL expireInRead;
static NSUInteger decorations;
static NSString *lastSender;
static NSData *lastPhoto;
static IMP originalDecoration;

@interface QAService : TeleGraphNotificationService @end
@implementation QAService
- (NSURL *)previewRoot {
    if (expireInRead) [self serviceExtensionTimeWillExpire];
    return testRoot;
}
@end

@interface QARecord : NSObject @end
@implementation QARecord
+ (UNNotificationContent *)decorateContent:(UNNotificationContent *)content account:(NSString *)account
                                      peer:(NSString *)peer sender:(NSString *)sender photo:(NSData *)photo
                              conversation:(NSString *)conversation {
    decorations++; lastSender = sender; lastPhoto = photo;
    // Original still runs: exercising real Intents + UserNotifications code.
    return ((UNNotificationContent *(*)(id, SEL, id, id, id, id, id, id))originalDecoration)(
        TGNotificationPresentation.class, _cmd, content, account, peer, sender, photo, conversation);
}
@end

static UNNotificationContent *deliver(NSDictionary *custom, NSString *key) {
    UNMutableNotificationContent *original = [UNMutableNotificationContent new];
    original.title = @"QA Sender"; original.body = @"Synthetic message";
    original.userInfo = @{@"user_id": @7, @"custom": custom,
        @"aps": @{@"alert": @{@"loc-key": key, @"loc-args": @[@"QA Sender", @"QA group"]}}};
    QAService *service = [QAService new];
    __block NSUInteger calls = 0;
    __block UNNotificationContent *received;
    [service didReceiveNotificationRequest:[UNNotificationRequest requestWithIdentifier:@"synthetic" content:original trigger:nil]
        withContentHandler:^(UNNotificationContent *content) { calls++; received = content; }];
    [service serviceExtensionTimeWillExpire];
    [service serviceExtensionTimeWillExpire];
    CHECK(calls == 1 && received != nil);
    return received;
}

int main(int argc, const char *argv[]) { @autoreleasepool {
    NSData *placeholder = [TGNotificationPresentation avatarData:nil name:@"QA Sender" sender:@"42"];
    UIImage *image = [UIImage imageWithData:placeholder];
    CHECK(image.size.width == 128 && image.size.height == 128);
    CHECK([placeholder isEqual:[TGNotificationPresentation avatarData:[@"broken" dataUsingEncoding:NSUTF8StringEncoding] name:@"QA Sender" sender:@"42"]]);
    CHECK([placeholder isEqual:[TGNotificationPresentation avatarData:[NSMutableData dataWithLength:512*1024+1] name:@"QA Sender" sender:@"42"]]);
    for (NSString *name in @[@"Ána López", @"👩🏽‍💻 Kai", @"李 雷", @"", @"..."]) {
        CHECK([UIImage imageWithData:[TGNotificationPresentation avatarData:nil name:name sender:@"42"]].size.width == 128);
    }
    UIGraphicsImageRendererFormat *format = [UIGraphicsImageRendererFormat defaultFormat]; format.scale = 1;
    NSData *photo = [[[UIGraphicsImageRenderer alloc] initWithSize:CGSizeMake(384,384) format:format]
        PNGDataWithActions:^(UIGraphicsImageRendererContext *ctx) { [UIColor.redColor setFill]; [ctx fillRect:CGRectMake(0,0,384,384)]; }];
    NSData *smallPhoto = [TGNotificationPresentation avatarData:photo name:@"QA Sender" sender:@"42"];
    CHECK(![smallPhoto isEqual:placeholder] && [UIImage imageWithData:smallPhoto].size.width == 128);
    UNMutableNotificationContent *content = [UNMutableNotificationContent new];
    content.title = @"QA Sender"; content.body = @"Synthetic message";
    INPerson *legacy = [[INPerson alloc] initWithPersonHandle:[[INPersonHandle alloc] initWithValue:@"7:42" type:INPersonHandleTypeUnknown]
        nameComponents:nil displayName:content.title image:nil contactIdentifier:nil customIdentifier:@"7:42"];
    INSendMessageIntent *legacyIntent = [[INSendMessageIntent alloc] initWithRecipients:nil outgoingMessageType:INOutgoingMessageTypeOutgoingMessageText
        content:nil speakableGroupName:nil conversationIdentifier:@"7:42" serviceName:@"TeleGraph" sender:legacy attachments:nil];
    CHECK(legacyIntent.sender.image == nil && [legacyIntent imageForParameterNamed:@"sender"] == nil);
    if (argc > 1) {
        NSURL *output = [NSURL fileURLWithPath:[NSString stringWithUTF8String:argv[1]] isDirectory:YES];
        [placeholder writeToURL:[output URLByAppendingPathComponent:@"initials-128.png"] atomically:YES];
        [smallPhoto writeToURL:[output URLByAppendingPathComponent:@"photo-synthetic-128.png"] atomically:YES];
        [[TGNotificationPresentation avatarData:[@"broken" dataUsingEncoding:NSUTF8StringEncoding] name:@"QA Sender" sender:@"42"]
            writeToURL:[output URLByAppendingPathComponent:@"corrupt-fallback-128.png"] atomically:YES];
    }
    for (id data in @[NSNull.null, photo]) {
        INSendMessageIntent *intent = [TGNotificationPresentation intentForContent:content account:@"7" peer:@"-99"
            sender:@"42" photo:data == NSNull.null ? nil : data conversation:@"QA group"];
        CHECK(intent.sender.image && [intent imageForParameterNamed:@"sender"]);
        CHECK([intent.sender.customIdentifier isEqual:@"7:42"] && [intent.conversationIdentifier isEqual:@"7:-99"]);
        CHECK([intent.sender.nameComponents.nickname isEqual:@"QA Sender"]);
        CHECK([intent.speakableGroupName.spokenPhrase isEqual:@"QA group"]);
        CHECK([intent.content isEqual:content.body]);
    }
    CHECK([TGNotificationPresentation decorateContent:content account:@"7" peer:@"42" sender:nil photo:photo conversation:nil] == content);

    SEL selector = @selector(decorateContent:account:peer:sender:photo:conversation:);
    originalDecoration = method_setImplementation(class_getClassMethod(TGNotificationPresentation.class, selector),
        method_getImplementation(class_getClassMethod(QARecord.class, selector)));
    testRoot = [[NSURL fileURLWithPath:NSTemporaryDirectory() isDirectory:YES] URLByAppendingPathComponent:NSUUID.UUID.UUIDString isDirectory:YES];
    [NSFileManager.defaultManager createDirectoryAtURL:[testRoot URLByAppendingPathComponent:@"7"] withIntermediateDirectories:YES attributes:nil error:nil];
    NSURL *policy = [testRoot URLByAppendingPathComponent:@"policy.plist"];
    [@{@"accounts": @[@7], @"generic": @"Private message"} writeToURL:policy atomically:YES];
    NSURL *cached = [testRoot URLByAppendingPathComponent:@"7/42.jpg"];
    NSDictionary *direct = @{@"msg_id": @11, @"from_id": @42};
    UNNotificationContent *notice = deliver(direct, @"MESSAGE_TEXT");
    CHECK(decorations == 1 && lastPhoto == nil && [lastSender isEqual:@"42"]);
    CHECK([notice.body isEqual:content.body]);
    [photo writeToURL:cached atomically:YES];
    deliver(direct, @"MESSAGE_TEXT"); CHECK([lastPhoto isEqual:photo]);
    [NSFileManager.defaultManager setAttributes:@{NSFileModificationDate: [NSDate dateWithTimeIntervalSinceNow:-4*86400]} ofItemAtPath:cached.path error:nil];
    deliver(direct, @"MESSAGE_TEXT"); CHECK(lastPhoto == nil);
    [@"broken" writeToURL:cached atomically:YES encoding:NSUTF8StringEncoding error:nil];
    notice = deliver(direct, @"MESSAGE_TEXT"); CHECK([notice.body isEqual:content.body]);
    for (NSString *senderField in @[@"chat_from_broadcast_id", @"chat_from_group_id"]) {
        notice = deliver(@{@"msg_id": @11, @"chat_id": @99, @"chat_from_id": @42, senderField: @81}, @"CHAT_MESSAGE_TEXT");
        CHECK([lastSender isEqual:@"-1000000000081"] && [notice.threadIdentifier isEqual:@"7:-99"]);
    }
    NSUInteger before = decorations;
    for (NSString *key in @[@"MESSAGE_NOTEXT", @"CHAT_MESSAGE_NO_TEXT", @"ENCRYPTED_MESSAGE", @"CHAT_MESSAGE_HIDDEN"]) deliver(direct, key);
    CHECK(decorations == before);
    deliver(@{@"msg_id": @11, @"from_id": @"../42"}, @"MESSAGE_TEXT"); CHECK(decorations == before);
    [@{@"accounts": @[], @"generic": @"Private message"} writeToURL:policy atomically:YES];
    notice = deliver(direct, @"MESSAGE_TEXT");
    CHECK(decorations == before && [notice.title isEqual:@"TeleGraph"] && [notice.body isEqual:@"Private message"]);
    [@{@"accounts": @[@7]} writeToURL:policy atomically:YES];
    expireInRead = YES;
    notice = deliver(direct, @"MESSAGE_TEXT");
    CHECK([notice.title isEqual:@"TeleGraph"] && [notice.body isEqual:@"New message"]);
    [NSFileManager.defaultManager removeItemAtURL:testRoot error:nil];
    puts("OK native avatars: real/missing/corrupt/oversized/Unicode; intent sender image; account/group policy; bounded expiry and exactly-once fallback");
    return 0;
} }
