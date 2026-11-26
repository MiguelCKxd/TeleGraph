"""Resolve the Siri/TV Objective-C entry points before sharing them with Core.

Rubicon lazily loads superclass method tables. Resolving two previously unused
class methods on different threads can race that initialization, even though the
native implementations themselves dispatch their UIKit work to the main queue.
The worker receives ordinary Python objects containing already-bound methods.
"""
from dataclasses import dataclass
from threading import current_thread, main_thread
from types import SimpleNamespace


@dataclass(frozen=True)
class CompanionBridges:
    vocabulary: object = None
    television: object = None

    def attach(self, core):
        """Called on the core loop only after native initialization has finished."""
        core.tv_link = self.television
        if self.vocabulary is not None:
            core.siri_vocabulary.attach(self.vocabulary, core)


def prepare_companions(class_factory=None):
    """Bind every selector on the UI thread, then start the TV listener.

Missing classes are supported for older native source builds. Other errors stay
visible; a broken bridge must not be silently presented as initialized.
"""
    if current_thread() is not main_thread():
        raise RuntimeError('iOS companion bridges must be prepared on the main thread.')
    if class_factory is None:
        from rubicon.objc import ObjCClass
        class_factory = ObjCClass

    try:
        native_vocabulary = class_factory('TGSiriVocabulary')
    except NameError:
        vocabulary = None
    else:
        vocabulary = SimpleNamespace(replaceJSON_=native_vocabulary.replaceJSON_)

    try:
        native_tv = class_factory('TGTVLink')
    except NameError:
        television = None
        start_tv = None
    else:
        # Resolve all methods used by the worker while NSObject's shared
        # metaclass cache is still confined to this thread. Never publish the
        # raw ObjCClass and leave selector lookup until a later worker call.
        start_tv = native_tv.start
        television = SimpleNamespace(
            disconnect=native_tv.disconnect,
            connectionID=native_tv.connectionID,
            share_connection_=native_tv.share_connection_,
            transportStatus=native_tv.transportStatus,
        )

    if start_tv is not None:
        start_tv()
    return CompanionBridges(vocabulary, television)
