import asyncio
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from tg_ascii.mac_media_access import ensure_media_access


class MacMediaAccessTests(unittest.IsolatedAsyncioTestCase):
    def framework(self, status, granted=True):
        device = NS(authorizationStatusForMediaType_=Mock(return_value=status),
            requestAccessForMediaType_completionHandler_=Mock(side_effect=lambda media, done: done(granted)))
        return NS(AVCaptureDevice=device, AVMediaTypeAudio='audio', AVMediaTypeVideo='video',
                  AVAuthorizationStatusAuthorized=3, AVAuthorizationStatusNotDetermined=0)

    async def test_already_authorized_never_prompts_again(self):
        framework = self.framework(3)
        with patch.dict('sys.modules', AVFoundation=framework), patch('tg_ascii.mac_media_access.sys', NS(platform='darwin')):
            await ensure_media_access(True)
        framework.AVCaptureDevice.requestAccessForMediaType_completionHandler_.assert_not_called()

    async def test_audio_request_does_not_request_camera(self):
        framework = self.framework(0)
        with patch.dict('sys.modules', AVFoundation=framework), patch('tg_ascii.mac_media_access.sys', NS(platform='darwin')):
            await ensure_media_access(False)
        calls = framework.AVCaptureDevice.requestAccessForMediaType_completionHandler_.call_args_list
        self.assertEqual([call.args[0] for call in calls], ['audio'])

    async def test_denied_access_does_not_open_repeated_permission_requests(self):
        framework = self.framework(2)
        with patch.dict('sys.modules', AVFoundation=framework), patch('tg_ascii.mac_media_access.sys', NS(platform='darwin')):
            with self.assertRaises(PermissionError): await ensure_media_access()
        framework.AVCaptureDevice.requestAccessForMediaType_completionHandler_.assert_not_called()

    async def test_os_rejection_stops_before_native_capture(self):
        framework = self.framework(0, granted=False)
        with patch.dict('sys.modules', AVFoundation=framework), patch('tg_ascii.mac_media_access.sys', NS(platform='darwin')):
            with self.assertRaises(PermissionError): await ensure_media_access()
