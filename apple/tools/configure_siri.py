"""Install the in-process UIKit SiriKit handler in the generated phone target."""
import os
from pathlib import Path
import plistlib
import shutil


def configure_siri(xcode):
    phone = xcode / 'TGASCII'
    source = Path(__file__).parent / 'ios' / 'TeleGraphSiri.m'
    shutil.copyfile(source, phone / source.name)
    vocabulary = source.with_name('TeleGraphSiriVocabulary.m')
    shutil.copyfile(vocabulary, phone / vocabulary.name)
    with (phone / source.name).open('a') as output:
        output.write('\n#import "TeleGraphSiriVocabulary.m"\n')
    main = phone / 'main.m'
    include = '#import "TeleGraphSiri.m"'
    text = main.read_text()
    presentation = source.with_name('TGNotificationPresentation.m')
    shutil.copyfile(presentation, phone / presentation.name)
    if '#import "TGNotificationPresentation.m"' not in text:
        text = '#import "TGNotificationPresentation.m"\n' + text
    if include not in text:
        text = f'#import <UIKit/UIKit.h>\n{include}\n' + text
    main.write_text(text)
    plist = phone / 'TGASCII-Info.plist'
    info = plistlib.loads(plist.read_bytes())
    actions = {'INSendMessageIntent', 'INSearchForMessagesIntent', 'INSetMessageAttributeIntent'}
    info['INIntentsSupported'] = sorted(actions | set(info.get('INIntentsSupported', ())))
    # The app's own lock (core.locked) does not cover a locked iPhone: without this key Siri would
    # read, send or mark TeleGraph messages from the lock screen. iOS asks to unlock first.
    info['INIntentsRestrictedWhileLocked'] = sorted(actions | set(info.get('INIntentsRestrictedWhileLocked', ())))
    info['NSSiriUsageDescription'] = 'Allow Siri to send messages and read messages from your TeleGraph account when you ask.'
    if os.environ.get('TELEGRAPH_CARPLAY') == '1':
        info['TeleGraphCarPlayEnabled'] = True
    else:
        info.pop('TeleGraphCarPlayEnabled', None)
    plist.write_bytes(plistlib.dumps(info))
    path = xcode / 'TeleGraphPush.entitlements'
    entitlements = plistlib.loads(path.read_bytes())
    entitlements['com.apple.developer.siri'] = True
    if os.environ.get('TELEGRAPH_CARPLAY') == '1':
        entitlements['com.apple.developer.carplay-communication'] = True
    else:
        entitlements.pop('com.apple.developer.carplay-communication', None)
    path.write_bytes(plistlib.dumps(entitlements))
