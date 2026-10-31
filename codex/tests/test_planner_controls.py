"""Independent user enable state and HQ suspension; migration preserves state."""
from pathlib import Path
import tempfile
import unittest
from tools.planner_controls import permission, migrate, user_command, finish_or_wait
from tools.planner_file_hook import handle

class PlannerControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.event=dict(session_id='target',hook_event_name='UserPromptSubmit')

    def test_start_and_stop_never_enable_or_disable_continuator(self):
        user_command(self.root,'stop');user_command(self.root,'start')
        self.assertEqual(permission(self.root),'idle')
        self.assertFalse((self.root/'continue_HQ').exists())
        user_command(self.root,'enable');before=(self.root/'continue_HQ').stat().st_mtime_ns
        for operation in ['stop','start','suspend','continue']:
            user_command(self.root,operation)
            self.assertEqual((self.root/'continue_HQ').stat().st_mtime_ns,before)
        finish_or_wait(self.root)
        self.assertEqual(permission(self.root),'stopped')
        self.assertEqual((self.root/'continue_HQ').stat().st_mtime_ns,before)

    def test_enable_and_disable_preserve_suspension(self):
        user_command(self.root,'stop');stamp=(self.root/'suspend_HQ').stat().st_mtime_ns
        user_command(self.root,'enable')
        self.assertEqual(permission(self.root),'stopped')
        user_command(self.root,'disable')
        self.assertEqual((self.root/'suspend_HQ').stat().st_mtime_ns,stamp)
        user_command(self.root,'start');user_command(self.root,'enable')
        user_command(self.root,'disable')
        self.assertEqual(permission(self.root),'idle')
        self.assertFalse((self.root/'suspend_HQ').exists())

    def test_migration_preserves_current_choice_and_old_stop(self):
        (self.root/'continue_planner').touch();(self.root/'stop_planner').touch()
        migrate(self.root);migrate(self.root)
        self.assertTrue((self.root/'continue_HQ').exists())
        self.assertEqual(permission(self.root),'stopped')
        self.assertFalse((self.root/'continue_planner').exists())
        user_command(self.root,'start');self.assertEqual(permission(self.root),'continue')
        (self.root/'Stop Goal').touch();self.assertEqual(permission(self.root),'stopped')
        migrate(self.root);self.assertTrue((self.root/'suspend_HQ').exists())

    def test_ancient_continue_never_enables_and_disabled_not_restored(self):
        (self.root/'Continue Goal').touch();migrate(self.root)
        self.assertEqual(permission(self.root),'idle')
        (self.root/'continue_planner').touch();user_command(self.root,'disable');migrate(self.root)
        self.assertEqual(permission(self.root),'idle')

    def test_hq_chat_and_planner_aliases_and_interrupt_preserve_enable_file(self):
        handle(dict(self.event,prompt='Включить континуатор'),'target',self.root)
        before=(self.root/'continue_HQ').stat().st_mtime_ns
        for stop,start in [('Остановить HQ','Продолжить HQ'),('Остановить штаб','Продолжить штаб'),('Stop Planner','Continue Planner'),('Остановить планер','Продолжай.')]:
            handle(dict(self.event,prompt=stop),'target',self.root)
            self.assertEqual(permission(self.root),'stopped')
            self.assertEqual(handle(dict(self.event,prompt=start),'target',self.root),{})
            self.assertEqual(permission(self.root),'continue')
        handle(dict(self.event,hook_event_name='Interrupt'),'target',self.root)
        self.assertTrue((self.root/'suspend_HQ').exists())
        self.assertEqual((self.root/'continue_HQ').stat().st_mtime_ns,before)
        handle(dict(self.event,prompt='Отключить континуатор'),'target',self.root)
        self.assertFalse((self.root/'continue_HQ').exists())
        self.assertTrue((self.root/'suspend_HQ').exists())

    def test_mentions_quoted_text_and_unrelated_chats_do_not_change_flags(self):
        for text in ['Что значит продолжай?','Пример: остановить HQ','<codex_delegation>Продолжай</codex_delegation>']:
            self.assertEqual(handle(dict(self.event,prompt=text),'target',self.root),{})
        handle(dict(self.event,prompt='Включить континуатор'),'other',self.root)
        self.assertEqual(list(self.root.iterdir()),[])
