"""Changing app language must not reload the external exam or reset timeouts."""
from test_browser import browser_widget, qt_app
from proctoring.i18n import set_language


def test_active_browser_language_changes_only_its_chrome(browser_widget):
    widget = browser_widget
    widget.start_exam()
    before_loads = list(widget.view.loads)
    before_deadline = widget._load_timeout.remainingTime()
    set_language("ru")
    assert widget.reload_button.text() == "Обновить"
    assert widget.status_label.text() == "Загрузка страницы экзамена…"
    assert widget.view.loads == before_loads
    assert widget._load_timeout.remainingTime() <= before_deadline
    widget._blocked("Navigation outside exam domain is blocked")
    set_language("kk")
    assert widget.status_label.text() == "Емтихан доменінен тыс өту бұғатталған"
    assert widget.reload_button.text() == "Қайта жүктеу"
    assert widget.view.loads == before_loads
    assert widget._navigation_blocked
    set_language("en")
    assert widget.status_label.text() == "Navigation outside exam domain is blocked"
    widget.stop()
    set_language("ru")
    assert widget.status_label.text() == "Сеанс браузера экзамена завершён."
    assert not widget.reload_button.isEnabled()
