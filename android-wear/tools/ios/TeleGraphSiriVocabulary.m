// Siri receives only the chat names selected in the active TeleGraph account.
@import UIKit;
@import Intents;

@interface TGSiriVocabulary : NSObject
+ (void)replaceJSON:(NSString *)json;
@end

@implementation TGSiriVocabulary
static NSArray *TGSelectedChats;
static BOOL TGDataUnavailable;

+ (void)applySelection {
    NSMutableOrderedSet *contacts = [NSMutableOrderedSet orderedSet];
    NSMutableOrderedSet *groups = [NSMutableOrderedSet orderedSet];
    if (!TGDataUnavailable && UIApplication.sharedApplication.protectedDataAvailable) {
        for (NSArray *row in TGSelectedChats) {
            INSpeakableString *term = [[INSpeakableString alloc] initWithVocabularyIdentifier:row[0]
                spokenPhrase:row[1] pronunciationHint:nil];
            // A group or channel can also be addressed as a single message recipient.
            [contacts addObject:term];
            if ([row[2] boolValue]) [groups addObject:term];
        }
    }
    INVocabulary *vocabulary = INVocabulary.sharedVocabulary;
    [vocabulary setVocabulary:contacts ofType:INVocabularyStringTypeContactName];
    [vocabulary setVocabulary:groups ofType:INVocabularyStringTypeContactGroupName];
}

+ (void)replaceJSON:(NSString *)json {
    NSArray *selection = [NSJSONSerialization JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];
    dispatch_async(dispatch_get_main_queue(), ^{
        static dispatch_once_t once;
        dispatch_once(&once, ^{
            NSNotificationCenter *center = NSNotificationCenter.defaultCenter;
            [center addObserverForName:UIApplicationProtectedDataWillBecomeUnavailable object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note) {
                TGSelectedChats = nil;
                TGDataUnavailable = YES;
                [self applySelection];
            }];
            [center addObserverForName:UIApplicationProtectedDataDidBecomeAvailable object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note) {
                // The core checks its own PIN and background timeout before republishing.
                TGDataUnavailable = NO;
            }];
        });
        TGSelectedChats = TGDataUnavailable ? nil : selection;
        [self applySelection];
    });
}
@end
