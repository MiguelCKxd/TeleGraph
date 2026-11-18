"""UI regressions with deterministic schedulers; no account, display or network needed."""
import asyncio
import queue
import tkinter as tk
import threading
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from tg_ascii.desktop import AsyncWorker, Desktop
from tg_ascii.scrolling import WheelRouter
from tg_ascii.ui_work import FrameJob, bind_text_action, clear_text_actions, sync_tree_rows


class Scheduler:
    def __init__(self):self.jobs={};self.serial=0;self.exists=True
    def winfo_exists(self):return self.exists
    def after(self,delay,callback):
        self.serial+=1;self.jobs[self.serial]=(delay,callback);return self.serial
    def after_cancel(self,ident):self.jobs.pop(ident,None)
    def flush(self):
        jobs=list(self.jobs.values());self.jobs.clear()
        for _,callback in jobs:callback()


class Tree:
    def __init__(self):
        self.rows={};self.order=[];self.writes=[]
        self.pack=Mock();self.pack_forget=Mock()
    def winfo_exists(self):return True
    def get_children(self):return tuple(self.order)
    def insert(self,parent,index,iid,**options):
        self.rows[iid]=options;self.order.append(iid);self.writes.append(('insert',iid))
    def item(self,iid,option=None,**options):
        if options:self.rows[iid].update(options);self.writes.append(('item',iid))
        return self.rows[iid].get(option) if option else self.rows[iid]
    def delete(self,*ids):
        for ident in ids:self.rows.pop(ident);self.order.remove(ident)
        if ids:self.writes.append(('delete',ids))
    def set_children(self,parent,*ids):self.order=list(ids);self.writes.append(('order',ids))


class UiWorkTests(TestCase):
    def test_identical_chat_refreshes_do_not_recreate_rows_or_images(self):
        tree=Tree();rows=[(str(i),f'Chat {i}') for i in range(1000)]
        sync_tree_rows(tree,rows);tree.rows['3']['image']=object();avatar=tree.rows['3']['image']
        tree.writes.clear()
        for _ in range(20):sync_tree_rows(tree,rows)
        self.assertEqual(tree.writes,[]);self.assertIs(tree.rows['3']['image'],avatar)
        rows[3]=('3','Chat 3 [1]');sync_tree_rows(tree,rows)
        self.assertEqual(tree.writes,[('item','3')]);self.assertIs(tree.rows['3']['image'],avatar)
        sync_tree_rows(tree,list(reversed(rows)))
        self.assertEqual(tree.order[0],'999');self.assertIs(tree.rows['3']['image'],avatar)
        sync_tree_rows(tree,[rows[3]])
        self.assertEqual(tree.order,['3']);self.assertIs(tree.rows['3']['image'],avatar)

    def test_dynamic_tags_release_registered_callbacks_after_every_render(self):
        commands={};serial=[0]
        def bind(tag,sequence,callback):
            serial[0]+=1;ident=str(serial[0]);commands[ident]=callback;return ident
        widget=NS(tag_bind=bind,tag_unbind=lambda tag,sequence,ident:commands.pop(ident))
        for _ in range(100):
            for i in range(30):bind_text_action(widget,str(i),'<Button-1>',lambda _:None)
            self.assertEqual(len(commands),30)
            bind_text_action(widget,'1','<Button-1>',lambda _:None)
            self.assertEqual(len(commands),30)
            clear_text_actions(widget);self.assertEqual(commands,{})

    def test_frame_job_coalesces_and_tolerates_window_destruction(self):
        root=Scheduler();callback=Mock();job=FrameJob(root,callback)
        for _ in range(500):job.request()
        self.assertEqual(len(root.jobs),1);root.flush();callback.assert_called_once()
        job.request();job.cancel();root.flush();callback.assert_called_once()
        root.exists=False;job.request();self.assertFalse(root.jobs)
        root.winfo_exists=Mock(side_effect=tk.TclError('destroyed'))
        job.request();job.run()
        root.after_cancel=Mock(side_effect=tk.TclError('destroyed'));job.job='old';job.cancel()
        self.assertIsNone(job.job)

    def app_for_messages(self,follow=True,count=0):
        app=object.__new__(Desktop)
        app.closed=app.closing=False;app.root=Scheduler();app.active=7
        app.preferences=NS(values={'bubbles':False});app.history=Mock()
        app.history.yview.return_value=(0,1 if follow else .5)
        app.messages=[NS(id=i,outgoing=True) for i in range(count)]
        app.chats=[];app.render_messages=Mock()
        return app

    def test_burst_merges_every_message_but_paints_once_and_bounds_live_tail(self):
        app=self.app_for_messages()
        for i in range(1000):app.incoming((7,NS(id=i,outgoing=True)))
        app.render_messages.assert_not_called();self.assertEqual(len(app.root.jobs),1)
        self.assertEqual([m.id for m in app.messages],list(range(800,1000)))
        app.root.flush();app.render_messages.assert_called_once_with(True)

    def test_explicit_history_pages_and_reading_position_are_preserved(self):
        app=self.app_for_messages(count=600)
        app.incoming((7,NS(id=600,outgoing=True)))
        self.assertEqual(len(app.messages),600);self.assertEqual(app.messages[0].id,1)
        app=self.app_for_messages(follow=False,count=600)
        app.incoming((7,NS(id=600,outgoing=True)))
        self.assertEqual(len(app.messages),601);self.assertEqual(app.messages[0].id,0)
        app.root.flush();app.render_messages.assert_called_once_with(False)

    def test_pointer_enter_only_installs_target_and_destroy_releases_remainder(self):
        bindings={};root=NS(bind_class=Mock(),bind_all=lambda seq,fn,**kw:bindings.update({seq:fn}))
        with patch.object(WheelRouter,'install') as install:
            router=WheelRouter(root);install.reset_mock();widget=object()
            bindings['<Enter>'](NS(widget=widget))
            install.assert_called_once_with(widget,recursive=False)
        router.remainders={(str(widget),'x'):.5,(str(widget),'y'):.3,('other','x'):.4}
        router.forget(NS(widget=widget));self.assertEqual(router.remainders,{('other','x'):.4})

    def test_event_pump_respects_frame_budget_without_losing_remaining_events(self):
        root=Scheduler();events=queue.SimpleQueue();callback=Mock()
        for i in range(200):events.put((callback,i))
        app=NS(closed=False,closing=False,root=root,worker=NS(events=events),show_error=Mock(),pump=Mock())
        with patch('tg_ascii.desktop.time.monotonic',side_effect=[0,.009]):Desktop.pump(app)
        callback.assert_called_once_with(0);self.assertEqual(events.qsize(),199)
        self.assertEqual(next(iter(root.jobs.values()))[0],8)


class SearchRobustnessTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.app=object.__new__(Desktop)
        app=self.app;app.root=Scheduler();app.demo=app.closed=app.closing=False
        app.ui_account='account';app.search=Mock();app.search.get.return_value='cats'
        app.global_results=Tree();app.search_more=Mock();app.search_records={};app.search_offset=None
        app.status=Mock();app.service=NS(backend=NS(search_public=AsyncMock(return_value=[]),global_messages=AsyncMock(return_value=([],None))))
        self.requests=[]
        def submit(coro,done,failed):
            job=Mock();self.requests.append((coro,done,failed,job));return job
        app.worker=NS(submit=submit)
    def tearDown(self):
        for coro,*_ in self.requests:coro.close()

    async def test_public_and_message_search_overlap_and_partial_failure_keeps_matches(self):
        app=self.app;public_started=asyncio.Event();messages_started=asyncio.Event()
        async def public(query):public_started.set();await messages_started.wait();raise OSError('offline')
        async def messages(query,offset):
            messages_started.set();await public_started.wait()
            return [(7,'Cats',NS(id=9,raw_text='hello',text='hello'))],None
        app.service.backend.search_public.side_effect=public
        app.service.backend.global_messages.side_effect=messages
        app.run_global_search();coro,done,*_=self.requests[-1]
        done(await asyncio.wait_for(coro,1))
        self.assertEqual(app.search_records,{'m7:9':('message',(7,9))})

    async def test_search_change_cancels_work_and_old_same_query_cannot_overwrite_results(self):
        app=self.app;app.run_global_search();_,old_done,old_failed,old_job=self.requests[-1]
        app.search.get.return_value='dogs';app.schedule_global_search();old_job.cancel.assert_called_once()
        app.search.get.return_value='cats';app.schedule_global_search();app.run_global_search()
        self.assertFalse(app.root.jobs)
        old_done(([NS(id=1,name='obsolete')],([],None)));old_failed(OSError())
        self.assertFalse(app.global_results.rows);app.status.set.assert_not_called()
        coro,done,*_=self.requests[-1];done(await coro)
        self.assertIsNone(app._search_job)

    async def test_more_has_one_inflight_request_and_captured_cursor(self):
        app=self.app;app.run_global_search();coro,done,*_=self.requests[-1]
        await coro;done(([],([],('cursor',))))
        app.run_global_search(True);app.run_global_search(True)
        self.assertEqual(len(self.requests),2)
        await self.requests[-1][0]
        app.service.backend.global_messages.assert_awaited_with('cats',('cursor',))

    async def test_failed_current_search_releases_request_and_short_query_cancels(self):
        app=self.app;app.run_global_search();_,_,failed,_=self.requests[-1]
        failed(TimeoutError());self.assertIsNone(app._search_job);app.status.set.assert_called_once()
        app.run_global_search();job=self.requests[-1][3]
        app.search.get.return_value='x';app.run_global_search();job.cancel.assert_called_once()
        self.assertIsNone(app._search_job);self.assertFalse(app.root.jobs)

    async def test_account_or_widget_rebuild_ignores_completed_request(self):
        app=self.app;app.run_global_search();_,done,failed,_=self.requests[-1]
        app.global_results=Tree()
        done(([NS(id=1,name='obsolete')],([],None)));failed(OSError())
        self.assertFalse(app.global_results.rows);app.status.set.assert_not_called()


class WorkerShutdownTests(TestCase):
    def test_shutdown_before_foreground_wrappers_run_releases_inner_operations(self):
        worker=AsyncWorker();started=threading.Event();release=threading.Event()
        def block_loop():started.set();release.wait(3)
        worker.loop.call_soon_threadsafe(block_loop);self.assertTrue(started.wait(3))
        app=NS(worker=worker,status=Mock(),update_controls=Mock(),show_error=Mock())
        async def operation():await asyncio.sleep(60)
        coroutines=[operation() for _ in range(30)]
        try:
            futures=[Desktop.call(app,coro,Mock(),'loading') for coro in coroutines]
            worker.stop();release.set();worker.thread.join(3)
            self.assertFalse(worker.thread.is_alive())
            self.assertTrue(all(future.cancelled() for future in futures))
            self.assertTrue(all(coro.cr_frame is None for coro in coroutines))
        finally:
            release.set();worker.stop();worker.thread.join(3)
            for coro in coroutines:coro.close()

    def test_foreground_call_after_shutdown_closes_inner_operation(self):
        async def operation():return 1
        coro=operation();app=NS(worker=NS(_stopping=True),status=Mock(),update_controls=Mock())
        result=Desktop.call(app,coro,Mock(),'loading')
        self.assertTrue(result.cancelled());self.assertIsNone(coro.cr_frame)
        app.status.set.assert_not_called();app.update_controls.assert_not_called()

    def test_submit_after_stop_closes_coroutine_and_returns_cancelled_future(self):
        worker=AsyncWorker();worker.stop();worker.stop();worker.thread.join(3)
        self.assertFalse(worker.thread.is_alive())
        async def operation():return 1
        coro=operation();callback=Mock();future=worker.submit(coro,callback,callback)
        self.assertTrue(future.cancelled());self.assertIsNone(coro.cr_frame)
        self.assertTrue(worker.events.empty());callback.assert_not_called()

    def test_cancel_before_task_starts_closes_submitted_coroutine(self):
        worker = AsyncWorker()
        start_scheduled = threading.Event()
        release = threading.Event()

        def pause_loop():
            start_scheduled.set()
            release.wait(3)

        worker.loop.call_soon_threadsafe(pause_loop)
        self.assertTrue(start_scheduled.wait(3))

        async def operation():
            self.fail('A cancelled operation must not start')

        coroutine = operation()
        callback = Mock()
        try:
            future = worker.submit(coroutine, callback, callback)
            self.assertTrue(future.cancel())
            worker.stop()
            release.set()
            worker.thread.join(3)
            self.assertIsNone(coroutine.cr_frame)
            self.assertTrue(worker.events.empty())
        finally:
            release.set()
            worker.stop()
            worker.thread.join(3)
            coroutine.close()

    def test_stop_cancels_inflight_task_without_delivering_ui_callbacks(self):
        worker=AsyncWorker();callback=Mock()
        async def operation():await asyncio.sleep(60)
        coroutine = operation()
        future=worker.submit(coroutine,callback,callback)
        worker.stop();worker.thread.join(3)
        self.assertFalse(worker.thread.is_alive());self.assertTrue(future.cancelled())
        self.assertIsNone(coroutine.cr_frame)
        self.assertTrue(worker.events.empty());callback.assert_not_called()
