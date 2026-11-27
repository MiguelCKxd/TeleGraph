// Shared by the phone and its Notification Service Extension. No network or credentials.
#import <UserNotifications/UserNotifications.h>
#import <Intents/Intents.h>
#import <UIKit/UIKit.h>
#import <ImageIO/ImageIO.h>

@interface TGNotificationPresentation : NSObject
+ (NSData *)avatarData:(NSData *)photo name:(NSString *)name sender:(NSString *)sender;
+ (INSendMessageIntent *)intentForContent:(UNNotificationContent *)content account:(NSString *)account
                                    peer:(NSString *)peer sender:(NSString *)sender photo:(NSData *)photo
                            conversation:(NSString *)conversation;
+ (UNNotificationContent *)decorateContent:(UNNotificationContent *)content account:(NSString *)account
                                      peer:(NSString *)peer sender:(NSString *)sender photo:(NSData *)photo
                              conversation:(NSString *)conversation;
@end

@implementation TGNotificationPresentation

+ (NSData *)avatarData:(NSData *)photo name:(NSString *)name sender:(NSString *)sender {
    // Bound both compressed input and decoded output. Corrupt/oversized/missing photos
    // use a presentation-only placeholder; they never become a profile photo in storage.
    if (photo.length && photo.length <= 512 * 1024) {
        CGImageSourceRef source = CGImageSourceCreateWithData((__bridge CFDataRef)photo,
            (__bridge CFDictionaryRef)@{(id)kCGImageSourceShouldCache: @NO});
        if (source) {
            CGImageRef image = CGImageSourceCreateThumbnailAtIndex(source, 0, (__bridge CFDictionaryRef)@{
                (id)kCGImageSourceCreateThumbnailFromImageAlways: @YES,
                (id)kCGImageSourceCreateThumbnailWithTransform: @YES,
                (id)kCGImageSourceThumbnailMaxPixelSize: @128,
                (id)kCGImageSourceShouldCacheImmediately: @YES});
            CFRelease(source);
            if (image) {
                NSData *result = UIImagePNGRepresentation([UIImage imageWithCGImage:image]);
                CGImageRelease(image);
                if (result.length) return result;
            }
        }
    }
    // Same seven gradients/id rule as tg_ascii.default_avatar. This NSData exists only
    // inside the intent; users with no photo remain photo-less in every model/cache.
    static const unsigned colours[][2] = {{0xFF845E,0xD45246},{0xFEBB5B,0xF68136},{0xB694F9,0x6C61DF},
        {0x9AD164,0x46BA43},{0x5BCBE3,0x359AD4},{0x5CAFFA,0x408ACF},{0xFF8AAC,0xD95574}};
    long long identifier = sender.longLongValue;
    if (identifier <= -1000000000000LL) identifier = -identifier - 1000000000000LL;
    NSUInteger index = llabs(identifier) % 7;
    NSMutableArray<NSString *> *words = [NSMutableArray array];
    for (NSString *word in [name componentsSeparatedByCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet]) {
        if (!word.length) continue;
        unichar first = [word characterAtIndex:0];
        if ([NSCharacterSet.alphanumericCharacterSet characterIsMember:first] || first > 127) [words addObject:word];
    }
    NSString *(^initial)(NSString *) = ^NSString *(NSString *word) {
        return [word substringWithRange:[word rangeOfComposedCharacterSequenceAtIndex:0]];
    };
    NSString *letters = words.count ? initial(words.firstObject) : @"?";
    if (words.count > 1) letters = [letters stringByAppendingString:initial(words.lastObject)];
    letters = letters.uppercaseString;
    UIGraphicsImageRendererFormat *format = [UIGraphicsImageRendererFormat defaultFormat];
    format.scale = 1; format.opaque = YES;
    UIGraphicsImageRenderer *renderer = [[UIGraphicsImageRenderer alloc] initWithSize:CGSizeMake(128,128) format:format];
    return [renderer PNGDataWithActions:^(UIGraphicsImageRendererContext *context) {
        CGFloat components[8];
        for (int stop = 0; stop < 2; ++stop) {
            unsigned colour = colours[index][stop];
            components[stop*4] = ((colour >> 16) & 255) / 255.0;
            components[stop*4+1] = ((colour >> 8) & 255) / 255.0;
            components[stop*4+2] = (colour & 255) / 255.0;
            components[stop*4+3] = 1;
        }
        CGColorSpaceRef space = CGColorSpaceCreateDeviceRGB();
        CGGradientRef gradient = CGGradientCreateWithColorComponents(space, components, NULL, 2);
        CGContextDrawLinearGradient(context.CGContext, gradient, CGPointZero, CGPointMake(0,128), 0);
        CGGradientRelease(gradient); CGColorSpaceRelease(space);
        NSDictionary *attributes = @{NSFontAttributeName: [UIFont systemFontOfSize:words.count > 1 ? 48 : 54 weight:UIFontWeightMedium],
                                     NSForegroundColorAttributeName: UIColor.whiteColor};
        CGSize size = [letters sizeWithAttributes:attributes];
        [letters drawAtPoint:CGPointMake((128-size.width)/2, (128-size.height)/2) withAttributes:attributes];
    }];
}

+ (INSendMessageIntent *)intentForContent:(UNNotificationContent *)content account:(NSString *)account
                                    peer:(NSString *)peer sender:(NSString *)sender photo:(NSData *)photo
                            conversation:(NSString *)conversation {
    if (!sender.length || !account.length || !content.title.length) return nil;
    NSString *identity = [NSString stringWithFormat:@"%@:%@", account, sender];
    INImage *image = [INImage imageWithImageData:[self avatarData:photo name:content.title sender:sender]];
    NSPersonNameComponents *name = [NSPersonNameComponents new];
    name.nickname = content.title;
    INPersonHandle *handle = [[INPersonHandle alloc] initWithValue:identity type:INPersonHandleTypeUnknown];
    INPerson *person = [[INPerson alloc] initWithPersonHandle:handle nameComponents:name displayName:content.title
        image:image contactIdentifier:nil customIdentifier:identity isMe:NO suggestionType:INPersonSuggestionTypeNone];
    INSpeakableString *group = conversation.length ? [[INSpeakableString alloc] initWithSpokenPhrase:conversation] : nil;
    INSendMessageIntent *intent = [[INSendMessageIntent alloc] initWithRecipients:nil
        outgoingMessageType:INOutgoingMessageTypeOutgoingMessageText content:content.body speakableGroupName:group
        conversationIdentifier:[NSString stringWithFormat:@"%@:%@", account, peer]
        serviceName:@"TeleGraph" sender:person attachments:nil];
    // In addition to INPerson.image, bind the image to the sender parameter, as the
    // official Telegram iOS client does. A group's own photo must not replace it.
    if (image) [intent setImage:image forParameterNamed:@"sender"];
    return intent;
}

+ (UNNotificationContent *)decorateContent:(UNNotificationContent *)content account:(NSString *)account
                                      peer:(NSString *)peer sender:(NSString *)sender photo:(NSData *)photo
                              conversation:(NSString *)conversation {
    INSendMessageIntent *intent = [self intentForContent:content account:account peer:peer sender:sender photo:photo conversation:conversation];
    if (!intent) return content;
    INInteraction *interaction = [[INInteraction alloc] initWithIntent:intent response:nil];
    interaction.direction = INInteractionDirectionIncoming;
    // Donation is best effort. Do not hold up or lose the alert waiting for Siri.
    [interaction donateInteractionWithCompletion:nil];
    return [content contentByUpdatingWithProvider:intent error:nil] ?: content;
}
@end
