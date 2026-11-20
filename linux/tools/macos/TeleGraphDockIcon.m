#import <AppKit/AppKit.h>
#import <ImageIO/ImageIO.h>
#import <fcntl.h>
#import <unistd.h>
#import <sys/stat.h>

@interface TeleGraphDockIcon : NSObject <NSDockTilePlugIn>
@property (nonatomic, strong) NSDockTile *tile;
@property (nonatomic, copy) NSString *identifier;
@end

@implementation TeleGraphDockIcon
- (void)setDockTile:(NSDockTile *)tile {
    NSDistributedNotificationCenter *center = NSDistributedNotificationCenter.defaultCenter;
    [center removeObserver:self];
    self.tile.contentView = nil;
    self.tile = tile;
    if (!tile) return;
    self.identifier = [[NSBundle bundleForClass:self.class].bundleIdentifier stringByDeletingPathExtension];
    [center addObserver:self selector:@selector(selectionChanged:) name:[self.identifier stringByAppendingString:@".dock-icon-changed"]
                 object:nil suspensionBehavior:NSNotificationSuspensionBehaviorDeliverImmediately];
    [self updateImage];
}

- (void)selectionChanged:(NSNotification *)notification {
    dispatch_async(dispatch_get_main_queue(), ^{ [self updateImage]; });
}

- (void)updateImage {
    if (!self.tile) return;
    NSURL *support = [NSFileManager.defaultManager URLsForDirectory:NSApplicationSupportDirectory inDomains:NSUserDomainMask].firstObject;
    NSURL *url = [[support URLByAppendingPathComponent:self.identifier isDirectory:YES] URLByAppendingPathComponent:@"DockIcon.png"];
    NSData *data = nil;
    int fd = open(url.fileSystemRepresentation, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (fd >= 0) {
        struct stat info;
        if (fstat(fd, &info) == 0 && S_ISREG(info.st_mode) && info.st_size > 0 && info.st_size <= 5 * 1024 * 1024) {
            NSFileHandle *file = [[NSFileHandle alloc] initWithFileDescriptor:fd closeOnDealloc:NO];
            data = [file readDataUpToLength:(NSUInteger)info.st_size error:nil];
        }
        close(fd);
    }
    CGImageSourceRef source = data ? CGImageSourceCreateWithData((__bridge CFDataRef)data, NULL) : NULL;
    NSImage *image = nil;
    if (source && CGImageSourceGetCount(source) == 1 && CGImageSourceGetType(source) &&
        CFEqual(CGImageSourceGetType(source), CFSTR("public.png"))) {
        NSDictionary *properties = CFBridgingRelease(CGImageSourceCopyPropertiesAtIndex(source, 0, NULL));
        NSInteger width = [properties[(__bridge NSString *)kCGImagePropertyPixelWidth] integerValue];
        NSInteger height = [properties[(__bridge NSString *)kCGImagePropertyPixelHeight] integerValue];
        if (width > 0 && width <= 1024 && height > 0 && height <= 1024) {
            CGImageRef pixels = CGImageSourceCreateImageAtIndex(source, 0, NULL);
            if (pixels) {
                image = [[NSImage alloc] initWithCGImage:pixels size:NSMakeSize(width, height)];
                CGImageRelease(pixels);
            }
        }
    }
    if (source) CFRelease(source);
    if (image) {
        NSImageView *view = [NSImageView imageViewWithImage:image];
        view.imageScaling = NSImageScaleProportionallyUpOrDown;
        self.tile.contentView = view;
    } else {
        self.tile.contentView = nil;
    }
    [self.tile display];
}
@end
