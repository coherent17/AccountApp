import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.main import MainWindow, create_app
from app.sample_data import load_sample_data
from app.animations import Ripple
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
app, ctx = create_app([sys.argv[0]], os.path.join(tempfile.mkdtemp(), "t.db"))
ctx.db.set_setting("owner_name", "游媽媽"); load_sample_data(ctx.db)
win = MainWindow(ctx); win.resize(1280, 800); win.show()
def pump(sec):
    end = time.perf_counter() + sec
    while time.perf_counter() < end:
        app.processEvents(); time.sleep(0.01)
pump(1.5)
win.go("accounts"); pump(0.30); win.grab().save(os.path.join(out, "a_transition.png"))
pump(1.0); win.grab().save(os.path.join(out, "b_countup_done.png"))
btn = win.nav_buttons["reports"]; Ripple(btn, btn.rect().center()); pump(0.12)
win.grab().save(os.path.join(out, "c_ripple.png"))
ctx.toast.emit("已儲存支出：155"); pump(0.5); win.grab().save(os.path.join(out, "d_toast.png"))
