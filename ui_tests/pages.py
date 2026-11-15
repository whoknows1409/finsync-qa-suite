"""Page objects: selectors live here, tests read like user stories."""

from __future__ import annotations

from playwright.sync_api import Page, expect


class LoginPage:
    def __init__(self, page: Page, base_url: str):
        self.page, self.base_url = page, base_url
        self.username = page.locator("#username")
        self.password = page.locator("#password")
        self.submit = page.locator("#login-btn")
        self.error = page.locator("#login-error")

    def open(self):
        self.page.goto(self.base_url)
        expect(self.username).to_be_visible()
        return self

    def login(self, user: str, password: str):
        self.username.fill(user)
        self.password.fill(password)
        self.submit.click()


class AppPage:
    def __init__(self, page: Page):
        self.page = page
        self.view = page.locator("#app-view")
        self.welcome = page.locator("#welcome")
        self.rows = page.locator("#tx-table tbody tr")
        self.chat_input = page.locator("#chat-input")
        self.send = page.locator("#send-btn")
        self.assistant_msgs = page.locator("#chat-log .msg.assistant")
        self.user_msgs = page.locator("#chat-log .msg.user")
        self.logout_btn = page.locator("#logout-btn")

    def wait_loaded(self):
        expect(self.view).to_be_visible()
        expect(self.rows.first).to_be_visible()
        return self

    def ask(self, text: str) -> str:
        """Send a message and return the assistant's next reply."""
        before = self.assistant_msgs.count()
        self.chat_input.fill(text)
        self.send.click()
        reply = self.assistant_msgs.nth(before)
        expect(reply).to_be_visible()
        return reply.inner_text()

    def logout(self):
        self.logout_btn.click()
