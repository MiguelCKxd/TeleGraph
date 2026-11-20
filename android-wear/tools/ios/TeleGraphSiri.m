// Compiled into the iPhone target. iOS launches the app in the background for SiriKit.
@import Intents;
@import UserNotifications;
#import <objc/runtime.h>

typedef void (^TGVoiceReply)(id);
@interface TGVoiceRequest : NSObject
@property(copy) NSString *payloadJSON;
@property(copy) TGVoiceReply reply;
@property(nonatomic, readonly) BOOL canAccessProtectedData;
- (void)finishJSON:(NSString *)json;
@end
@implementation TGVoiceRequest
- (BOOL)canAccessProtectedData {
    if (NSThread.isMainThread) return UIApplication.sharedApplication.protectedDataAvailable;
    __block BOOL available = NO;
    dispatch_sync(dispatch_get_main_queue(), ^{ available = UIApplication.sharedApplication.protectedDataAvailable; });
    return available;
}
- (void)finishJSON:(NSString *)json {
    TGVoiceReply reply = self.reply;
    self.reply = nil;
    if (reply) reply(json && self.canAccessProtectedData ? [NSJSONSerialization JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil] : nil);
}
@end

@interface TGVoiceHandler : NSObject <INSendMessageIntentHandling, INSearchForMessagesIntentHandling, INSetMessageAttributeIntentHandling>
@end
static void (^TGVoiceDispatch)(TGVoiceRequest *);
static TGVoiceHandler *TGVoiceSingleton;
static id TGHandlerForIntent(id delegate, SEL selector, UIApplication *app, INIntent *intent) {
    if ([intent isKindOfClass:INSendMessageIntent.class] || [intent isKindOfClass:INSearchForMessagesIntent.class] ||
        [intent isKindOfClass:INSetMessageAttributeIntent.class]) return TGVoiceSingleton;
    return nil;
}
static void TGVoiceRun(NSDictionary *payload, TGVoiceReply reply) {
    TGVoiceRequest *req = [TGVoiceRequest new];
    if (!req.canAccessProtectedData) { reply(nil); return; }
    req.payloadJSON = [[NSString alloc] initWithData:[NSJSONSerialization dataWithJSONObject:payload options:0 error:nil] encoding:NSUTF8StringEncoding];
    req.reply = reply;
    TGVoiceDispatch(req);
}
static INPerson *TGVoicePerson(NSString *key, NSString *name) {
    INPersonHandle *handle = [[INPersonHandle alloc] initWithValue:key type:INPersonHandleTypeUnknown];
    return [[INPerson alloc] initWithPersonHandle:handle nameComponents:nil displayName:name image:nil contactIdentifier:nil customIdentifier:key];
}
@implementation TGVoiceHandler
+ (void)install:(void (^)(TGVoiceRequest *))dispatch {
    TGVoiceSingleton = [self new];
    TGVoiceDispatch = [dispatch copy];
    class_addMethod(NSClassFromString(@"PythonAppDelegate"), @selector(application:handlerForIntent:), (IMP)TGHandlerForIntent, "@@:@@");
}
- (void)resolveRecipientsForSendMessage:(INSendMessageIntent *)intent completion:(void (^)(NSArray<INSendMessageRecipientResolutionResult *> *))completion {
    Class result = INSendMessageRecipientResolutionResult.class;
    if (!intent.recipients.count) { completion(@[[result needsValue]]); return; }
    if (intent.recipients.count != 1) { completion(@[[result unsupported]]); return; }
    INPerson *candidate = intent.recipients.firstObject;
    TGVoiceRun(@{@"op":@"resolve", @"name":candidate.displayName ?: @"", @"id":candidate.customIdentifier ?: @""}, ^(NSArray *matches) {
        NSMutableArray *people = [NSMutableArray array];
        for (NSDictionary *match in matches) [people addObject:TGVoicePerson(match[@"id"],match[@"name"])];
        id answer = people.count > 1 ? [result disambiguationWithPeopleToDisambiguate:people] :
                    people.count == 1 ? [result successWithResolvedPerson:people.firstObject] : [result unsupported];
        completion(@[answer]);
    });
}
- (void)resolveContentForSendMessage:(INSendMessageIntent *)intent withCompletion:(void (^)(INStringResolutionResult *))completion {
    completion(intent.content.length ? [INStringResolutionResult successWithResolvedString:intent.content] : [INStringResolutionResult needsValue]);
}
- (void)handleSendMessage:(INSendMessageIntent *)intent completion:(void (^)(INSendMessageIntentResponse *))completion {
    NSString *conversation = intent.conversationIdentifier ?: intent.recipients.firstObject.customIdentifier;
    if (intent.recipients.count > 1 || !conversation.length || !intent.content.length) {
        completion([[INSendMessageIntentResponse alloc] initWithCode:INSendMessageIntentResponseCodeFailure userActivity:nil]); return;
    }
    TGVoiceRun(@{@"op":@"send", @"conversation":conversation, @"text":intent.content}, ^(id result) {
        completion([[INSendMessageIntentResponse alloc] initWithCode:result ? INSendMessageIntentResponseCodeSuccess : INSendMessageIntentResponseCodeFailure userActivity:nil]);
    });
}
- (void)handleSearchForMessages:(INSearchForMessagesIntent *)intent completion:(void (^)(INSearchForMessagesIntentResponse *))completion {
    if (intent.senders.count || intent.recipients.count || intent.dateTimeRange || intent.speakableGroupNames.count ||
        (intent.notificationIdentifiers.count && intent.notificationIdentifiersOperator == INConditionalOperatorNone) ||
        (intent.attributes & ~INMessageAttributeOptionUnread)) {
        completion([[INSearchForMessagesIntentResponse alloc] initWithCode:INSearchForMessagesIntentResponseCodeFailure userActivity:nil]); return;
    }
    NSMutableDictionary *query = [@{@"op":@"search", @"unread":@(!!(intent.attributes & INMessageAttributeOptionUnread)),
                  @"ids":intent.identifiers ?: @[], @"terms":intent.searchTerms ?: @[], @"conversations":intent.conversationIdentifiers ?: @[]} mutableCopy];
    TGVoiceReply respond = ^(NSArray *records) {
        INSearchForMessagesIntentResponse *response = [[INSearchForMessagesIntentResponse alloc]
            initWithCode:records ? INSearchForMessagesIntentResponseCodeSuccess : INSearchForMessagesIntentResponseCodeFailure userActivity:nil];
        NSMutableArray *messages = [NSMutableArray array];
        for (NSDictionary *r in records) {
            [messages addObject:[[INMessage alloc] initWithIdentifier:r[@"id"] conversationIdentifier:r[@"chat"] content:r[@"text"]
                dateSent:[NSDate dateWithTimeIntervalSince1970:[r[@"date"] doubleValue]] sender:TGVoicePerson(r[@"sender"], r[@"name"])
                recipients:nil groupName:nil messageType:INMessageTypeText serviceName:@"TeleGraph"]];
        }
        response.messages = messages;
        completion(response);
    };
    if (!intent.notificationIdentifiers.count) { TGVoiceRun(query, respond); return; }
    NSSet *wanted = [NSSet setWithArray:intent.notificationIdentifiers];
    if (wanted.count > 1 && intent.notificationIdentifiersOperator == INConditionalOperatorAll) {
        respond(@[]); return;
    }
    [UNUserNotificationCenter.currentNotificationCenter getDeliveredNotificationsWithCompletionHandler:^(NSArray<UNNotification *> *delivered) {
        NSMutableArray *routes = [NSMutableArray array];
        for (UNNotification *notice in delivered) {
            UNNotificationContent *content = notice.request.content;
            if (![wanted containsObject:notice.request.identifier] || ![content.categoryIdentifier isEqualToString:@"TeleGraphMessage"]) continue;
            NSArray *route = content.userInfo[@"TeleGraphMessageRoute"];
            if ([route isKindOfClass:NSArray.class] && route.count == 3) [routes addObject:route];
        }
        if (!routes.count) { respond(@[]); return; }
        query[@"notificationRoutes"] = routes;
        TGVoiceRun(query, respond);
    }];
}
- (void)handleSetMessageAttribute:(INSetMessageAttributeIntent *)intent completion:(void (^)(INSetMessageAttributeIntentResponse *))completion {
    if (intent.attribute != INMessageAttributeRead || !intent.identifiers.count) {
        completion([[INSetMessageAttributeIntentResponse alloc] initWithCode:INSetMessageAttributeIntentResponseCodeFailureMessageAttributeNotSet userActivity:nil]); return;
    }
    TGVoiceRun(@{@"op":@"read", @"ids":intent.identifiers}, ^(id result) {
        completion([[INSetMessageAttributeIntentResponse alloc] initWithCode:result ? INSetMessageAttributeIntentResponseCodeSuccess : INSetMessageAttributeIntentResponseCodeFailure userActivity:nil]);
    });
}
@end
