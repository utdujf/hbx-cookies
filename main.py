import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import instaloader
import pyotp
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.properties import BooleanProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.cardview import CardView
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.utils import platform

if platform == 'android':
    from android.permissions import request_permissions, Permission
    request_permissions([Permission.INTERNET, Permission.WRITE_EXTERNAL_STORAGE, Permission.READ_EXTERNAL_STORAGE])

class HBXCard(CardView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (1, None)
        self.height = 520
        self.elevation = 8
        self.background_color = (0.98, 0.98, 0.98, 1)
        self.radius = [24]

class HBXAppLayout(BoxLayout):
    is_running = BooleanProperty(False)
    total = NumericProperty(0)
    processed = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = [16, 16, 16, 16]
        self.spacing = 14

        header = BoxLayout(size_hint_y=0.12)
        self.app_title = Label(text='HBX COOKIES', font_size='24sp', bold=True, color=(0.2, 0.2, 0.2, 1))
        header.add_widget(Image(source='', size_hint_x=0.2))
        header.add_widget(self.app_title)
        self.add_widget(header)

        self.card = HBXCard()
        main_box = BoxLayout(orientation='vertical', padding=[20, 20, 20, 20], spacing=12)

        self.usernames = TextInput(hint_text='Usernames (one per line)', multiline=True, size_hint_y=0.25,
                                   background_color=(0.95, 0.95, 0.95, 1), foreground_color=(0,0,0,1))
        self.password = TextInput(hint_text='Common password', password=True, size_hint_y=0.12,
                                  background_color=(0.95,0.95,0.95,1), foreground_color=(0,0,0,1))
        self.keys = TextInput(hint_text='2FA keys (one per line)', multiline=True, size_hint_y=0.25,
                              background_color=(0.95,0.95,0.95,1), foreground_color=(0,0,0,1))

        btn_box = BoxLayout(size_hint_y=0.12, spacing=12)
        self.start_btn = Button(text='START', background_color=(0.2, 0.6, 0.2, 1), color=(1,1,1,1))
        self.cancel_btn = Button(text='CANCEL', background_color=(0.7, 0.2, 0.2, 1), color=(1,1,1,1), disabled=True)
        self.start_btn.bind(on_press=self.start_processing)
        self.cancel_btn.bind(on_press=self.cancel_processing)
        btn_box.add_widget(self.start_btn)
        btn_box.add_widget(self.cancel_btn)

        self.progress_bar = ProgressBar(size_hint_y=0.06, max=100)
        self.progress_label = Label(text='0 / 0', size_hint_y=0.06, color=(0.3,0.3,0.3,1))

        log_scroll = ScrollView(size_hint_y=0.35, do_scroll_x=False)
        self.log_area = BoxLayout(orientation='vertical', size_hint_y=None)
        self.log_area.bind(minimum_height=self.log_area.setter('height'))
        log_scroll.add_widget(self.log_area)

        self.export_btn = Button(text='📁 EXPORT RESULTS', size_hint_y=0.1, background_color=(0.1,0.5,0.8,1), disabled=True)
        self.export_btn.bind(on_press=self.export_results)

        main_box.add_widget(self.usernames)
        main_box.add_widget(self.password)
        main_box.add_widget(self.keys)
        main_box.add_widget(btn_box)
        main_box.add_widget(self.progress_bar)
        main_box.add_widget(self.progress_label)
        main_box.add_widget(log_scroll)
        main_box.add_widget(self.export_btn)

        self.card.add_widget(main_box)
        self.add_widget(self.card)

        self.executor = None
        self.cancel_flag = False
        self.results = []
        self.succ = 0
        self.fail = 0

    def add_log(self, text, color=(0.2,0.2,0.2,1)):
        log = Label(text=text, size_hint_y=None, height=26, color=color, font_size='12sp')
        log.bind(texture_size=log.setter('size'))
        self.log_area.add_widget(log)
        if self.parent and self.parent.children[0]:
            Clock.schedule_once(lambda dt: setattr(self.parent.children[0], 'scroll_y', 0))

    def start_processing(self, inst):
        if self.is_running:
            return
        usernames = [u.strip() for u in self.usernames.text.splitlines() if u.strip()]
        password = self.password.text.strip()
        keys = [k.strip() for k in self.keys.text.splitlines() if k.strip()]

        if not usernames:
            self.add_log('❌ No usernames', (0.8,0.2,0.2,1))
            return
        if not password:
            self.add_log('❌ Password empty', (0.8,0.2,0.2,1))
            return
        if len(usernames) != len(keys):
            self.add_log(f'❌ Mismatch: {len(usernames)} users vs {len(keys)} keys', (0.8,0.2,0.2,1))
            return

        self.total = len(usernames)
        self.processed = 0
        self.succ = 0
        self.fail = 0
        self.results = []
        self.cancel_flag = False
        self.start_btn.disabled = True
        self.cancel_btn.disabled = False
        self.export_btn.disabled = True
        self.is_running = True
        self.progress_bar.value = 0
        self.progress_label.text = '0 / ' + str(self.total)
        self.log_area.clear_widgets()
        self.add_log('🔄 Starting HBX engine...', (0.2,0.5,0.8,1))

        threading.Thread(target=self._process, args=(usernames, password, keys), daemon=True).start()

    def _process(self, users, pwd, keys):
        max_workers = min(10, len(users))
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        futures = []
        for u, k in zip(users, keys):
            if self.cancel_flag:
                break
            futures.append(self.executor.submit(self._login_worker, u, pwd, k))

        for f in futures:
            if self.cancel_flag:
                f.cancel()
            else:
                try:
                    f.result()
                except Exception as e:
                    self._ui_fail(u, str(e))
        self.executor.shutdown(wait=False)
        Clock.schedule_once(lambda dt: self._finish())

    def _login_worker(self, username, password, key):
        if self.cancel_flag:
            return
        try:
            L = instaloader.Instaloader(quiet=True, max_connection_attempts=1)
            L.context._session.headers.update({'User-Agent': 'Mozilla/5.0 (Linux; Android 13) Instagram 269.0.0.18.78'})
            L.login(username, password)
            self._login_success(L, username, password)
        except instaloader.exceptions.TwoFactorAuthRequiredException:
            try:
                totp = pyotp.TOTP(key.replace(' ', ''))
                L.two_factor_login(totp.now())
                self._login_success(L, username, password)
            except Exception as e:
                self._ui_fail(username, f'2FA error: {str(e)[:60]}')
        except Exception as e:
            self._ui_fail(username, str(e)[:80])

    def _login_success(self, L, username, password):
        cookies = L.context._session.cookies.get_dict()
        cookie_str = '; '.join([f'{k}={v}' for k,v in cookies.items()])
        self.results.append(f'{username}|{password}|{cookie_str}')
        self._ui_success(username)

    def _ui_success(self, username):
        self.succ += 1
        self.processed += 1
        Clock.schedule_once(lambda dt: self._update_ui(username, f'✅ {username} -> cookie saved', (0,0.7,0,1)))

    def _ui_fail(self, username, err):
        self.fail += 1
        self.processed += 1
        Clock.schedule_once(lambda dt: self._update_ui(username, f'❌ {username} : {err}', (0.7,0.2,0.2,1)))

    def _update_ui(self, username, msg, color):
        self.add_log(msg, color)
        self.progress_bar.value = (self.processed / self.total) * 100
        self.progress_label.text = f'{self.processed} / {self.total}'

    def _finish(self):
        self.is_running = False
        self.start_btn.disabled = False
        self.cancel_btn.disabled = True
        self.add_log(f'\n🏁 DONE – Success: {self.succ}, Failed: {self.fail}', (0.3,0.6,0.9,1))
        if self.results:
            self.export_btn.disabled = False

    def cancel_processing(self, inst):
        self.cancel_flag = True
        self.add_log('⚠️ Cancelling tasks...', (0.9,0.5,0,1))
        self.cancel_btn.disabled = True

    def export_results(self, inst):
        if not self.results:
            self.add_log('No results to export', (0.8,0.2,0.2,1))
            return
        filename = f'HBX_cookies_{int(time.time())}.txt'
        if platform == 'android':
            from android.storage import primary_external_storage_path
            path = primary_external_storage_path() or '/sdcard'
            filepath = os.path.join(path, 'Download', filename)
        else:
            filepath = filename
        try:
            with open(filepath, 'w') as f:
                f.write('\n'.join(self.results))
            self.add_log(f'📁 Saved: {filepath}', (0,0.6,0.3,1))
        except Exception as e:
            self.add_log(f'Export failed: {e}', (0.8,0.2,0.2,1))

class HBXCookiesApp(App):
    def build(self):
        Window.clearcolor = (0.94, 0.94, 0.96, 1)
        return HBXAppLayout()

if __name__ == '__main__':
    HBXCookiesApp().run()
