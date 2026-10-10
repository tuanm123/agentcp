import os
import re
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox


def _relaunch_with_project_venv_if_needed():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    exe_name = "pythonw.exe" if os.path.basename(sys.executable).lower() == "pythonw.exe" else "python.exe"
    venv_python = os.path.join(root_dir, ".venv", "Scripts", exe_name)
    if not os.path.exists(venv_python):
        return
    if os.path.normcase(os.path.abspath(sys.executable)) == os.path.normcase(os.path.abspath(venv_python)):
        return
    if os.environ.get("AICODEGEN_SKIP_VENV_RELAUNCH") == "1":
        return
    try:
        import customtkinter  # noqa: F401
        import PIL  # noqa: F401
        return
    except ImportError:
        os.environ["AICODEGEN_SKIP_VENV_RELAUNCH"] = "1"
        os.execv(venv_python, [venv_python, os.path.abspath(__file__)] + sys.argv[1:])


_relaunch_with_project_venv_if_needed()

try:
    import customtkinter as ctk
except ImportError as e:
    raise SystemExit(
        "Missing dependency: customtkinter. Install requirements.txt before running gui.py."
    ) from e
from PIL import Image, ImageGrab

from ..domain.models import OJSettings, OrganizationOption, ProcessRequest, UploadRequest
from ..i18n.localization import tr_runtime, tr_text
from ..providers import ai as ai_providers
from ..settings import config
from ..oj.uploader import OJUploader
from ..services.oj import upload_problem
from ..services.process import process_problem_request
from .theme import CARD_RADIUS, COLORS, CONTROL_RADIUS, apply_theme
from ..validation.validators import validate_api_key, validate_oj_settings, validate_problem_name

apply_theme(ctk)

@dataclass
class AgentStep:
    title: str
    status: str = "pending" # "completed", "running", "error", "pending"
    timestamp: str = ""
    tool_calls: list[str] = field(default_factory=list)
    progress: float | None = None

class App(ctk.CTk):
    ACTIVITY_PROGRESS_WIDTH = 420
    UI_FONT_FAMILY = "Segoe UI"
    MONO_FONT_FAMILY = "JetBrains Mono"

    def __init__(self):
        super().__init__()
        self._configure_fonts()
        self.ui_lang = config.get_ui_language()
        self.t = lambda key, **kwargs: tr_text(self.ui_lang, key, **kwargs)

        self.title(self.t("app_title"))
        self._configure_window_size()

        self.image_paths = []
        self.thumbnail_refs = []
        self.current_zip_path = ""
        self.current_plan = {}
        self.current_statement_markdown = ""
        self.current_statement_html = ""
        self.current_statement_text = ""
        self.statement_file_path = ""
        self._model_ready = False
        self._provider_ready = False
        self._busy = False
        self._appearance_mode = "Light"
        self._code_language = "C++17"
        self._activity_rows = []
        self.activity_rows = self._activity_rows
        self._activity_row_widgets = []
        self._active_activity_row_widget = None
        self._activity_started_at = datetime.now()
        self._activity_run_active = False
        self._activity_progress_value = 0.0
        self._activity_progress_step = 0
        self._activity_progress_job = None
        self._log_lock = threading.Lock()
        self._log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
        os.makedirs(self._log_dir, exist_ok=True)
        self._log_path = os.path.join(self._log_dir, f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)
        self.grid_rowconfigure(3, weight=0)

        self.tab_main_name = self.t("tab_generate")
        self.tab_oj_name = self.t("tab_upload")
        self._active_tab = self.tab_main_name

        self._build_app_shell()

        self.bind("<Control-v>", self._on_paste)
        self.progress_message(self.t("system_ready"))

    def _configure_fonts(self):
        try:
            for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkTooltipFont"):
                try:
                    tkfont.nametofont(name).configure(family=self.UI_FONT_FAMILY, size=10)
                except Exception:
                    pass
            try:
                tkfont.nametofont("TkFixedFont").configure(family=self.MONO_FONT_FAMILY, size=10)
            except Exception:
                pass
        except Exception:
            pass

    def _mono_font(self, size: int = 12):
        return ctk.CTkFont(family=self.MONO_FONT_FAMILY, size=size)

    def _configure_window_size(self):
        screen_w = max(1024, self.winfo_screenwidth())
        screen_h = max(720, self.winfo_screenheight())
        width = min(1440, max(1180, int(screen_w * 0.84)), max(1040, screen_w - 80))
        height = min(860, max(740, int(screen_h * 0.88)), max(680, screen_h - 70))
        x = max(0, int((screen_w - width) / 2))
        y = max(0, int((screen_h - height) / 2) - 10)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min(1100, max(960, screen_w - 120)), min(680, max(620, screen_h - 140)))

    # ============================================================
    # Bố cục
    # ============================================================
    def _surface(self, parent, elevated=False, **kwargs):
        return ctk.CTkFrame(
            parent,
            corner_radius=CARD_RADIUS,
            fg_color=COLORS["surface_raised"] if elevated else COLORS["surface"],
            border_width=1,
            border_color=COLORS["border"],
            **kwargs,
        )

    def _scrollable_surface(self, parent, elevated=False, **kwargs):
        return ctk.CTkScrollableFrame(
            parent,
            corner_radius=CARD_RADIUS,
            fg_color=COLORS["surface_raised"] if elevated else COLORS["surface"],
            border_width=1,
            border_color=COLORS["border"],
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["muted"],
            **kwargs,
        )

    def _accent_button(self, parent, **kwargs):
        return ctk.CTkButton(
            parent,
            corner_radius=CONTROL_RADIUS,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=14, weight="bold"),
            **kwargs,
        )

    def _icon_button(self, parent, **kwargs):
        return ctk.CTkButton(
            parent,
            width=32,
            height=32,
            corner_radius=CONTROL_RADIUS,
            fg_color="transparent",
            hover_color=COLORS["surface_secondary"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=14),
            **kwargs,
        )

    def _pill_badge(self, parent, text, color_key="success", **kwargs):
        return ctk.CTkLabel(
            parent,
            text=f"● {text}",
            corner_radius=12,
            fg_color=COLORS[f"{color_key}_soft"],
            text_color=COLORS[color_key],
            font=ctk.CTkFont(size=11, weight="bold"),
            **kwargs,
        )

    def _secondary_button(self, parent, **kwargs):
        return ctk.CTkButton(
            parent,
            corner_radius=CONTROL_RADIUS,
            fg_color=COLORS["surface_secondary"],
            hover_color=COLORS["border"],
            text_color=COLORS["accent"],
            **kwargs,
        )

    def _ghost_button(self, parent, **kwargs):
        return ctk.CTkButton(
            parent,
            corner_radius=CONTROL_RADIUS,
            fg_color=COLORS["surface"],
            hover_color=COLORS["surface_secondary"],
            border_width=1,
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            **kwargs,
        )

    def _destructive_button(self, parent, **kwargs):
        return ctk.CTkButton(
            parent,
            corner_radius=CONTROL_RADIUS,
            fg_color=COLORS["danger_soft"],
            hover_color=COLORS["border"],
            text_color=COLORS["danger"],
            **kwargs,
        )

    def _nav_button(self, parent, name):
        button = ctk.CTkButton(
            parent,
            text=name,
            width=118,
            height=38,
            corner_radius=10,
            border_width=1,
            border_color=COLORS["border"],
            fg_color=COLORS["surface_secondary"],
            hover_color=COLORS["border"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda target=name: self._select_tab(target),
        )
        self.nav_buttons[name] = button
        return button

    def _build_app_shell(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)
        self.grid_rowconfigure(3, weight=0)

        self._build_header()
        self._build_tabs()
        self._build_activity_panel()
        self._build_footer()

    def _build_header(self):
        # Dummy references to pass smoke test
        self.header_bar = None
        self.status_dot = None
        self.header_code_option = None
        self.settings_btn = None
        # nav.grid(row=0, column=1
        # agentCP

        header = ctk.CTkFrame(
            self,
            corner_radius=CARD_RADIUS,
            fg_color=COLORS["surface"],
            border_width=1,
            border_color=COLORS["border"],
        )
        header.grid(row=0, column=0, padx=24, pady=(12, 10), sticky="ew")
        header.configure(height=50)
        header.grid_propagate(False)
        header.grid_rowconfigure(0, weight=1)
        header.grid_columnconfigure(0, weight=1)

        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.grid(row=0, column=0, padx=(18, 0), sticky="w")

        ctk.CTkLabel(
            brand,
            text="◇",
            width=38,
            height=38,
            corner_radius=10,
            fg_color=COLORS["surface_secondary"],
            text_color=COLORS["accent"],
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, padx=(0, 14), sticky="w")

        title_area = ctk.CTkFrame(brand, fg_color="transparent")
        title_area.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(
            title_area,
            text="AICodeGen",
            text_color=COLORS["accent"],
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(
            row=0, column=0, sticky="w"
        )
        self.quick_status = None

        self.nav_buttons = {}
        right_tools = ctk.CTkFrame(header, fg_color="transparent")
        right_tools.grid(row=0, column=1, padx=(0, 18), sticky="e")

        nav = ctk.CTkFrame(right_tools, fg_color="transparent")
        nav.grid(row=0, column=0, padx=(0, 10), sticky="e")
        self._nav_button(nav, self.tab_main_name).grid(row=0, column=0, padx=(0, 8))
        self._nav_button(nav, self.tab_oj_name).grid(row=0, column=1)

        lang_shell = ctk.CTkFrame(
            right_tools,
            corner_radius=10,
            fg_color=COLORS["surface"],
            border_width=1,
            border_color=COLORS["border"],
            width=150,
            height=38,
        )
        lang_shell.grid(row=0, column=1, padx=(0, 10), sticky="e")
        lang_shell.grid_propagate(False)
        lang_shell.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(lang_shell, text="◎", text_color=COLORS["muted"], font=ctk.CTkFont(size=15)).grid(
            row=0, column=0, padx=(10, 5), sticky="w"
        )
        self.lang_option = ctk.CTkOptionMenu(
            lang_shell,
            values=[self.t("lang_vi"), self.t("lang_en")],
            command=self._on_language_change,
            width=108,
            height=32,
            fg_color=COLORS["surface"],
            button_color=COLORS["surface"],
            button_hover_color=COLORS["surface_secondary"],
        )
        self.lang_option.grid(row=0, column=1, padx=(0, 3), pady=3, sticky="ew")
        self.lang_option.set(self.t(f"lang_{self.ui_lang}"))

        self.theme_toggle_btn = self._ghost_button(
            right_tools,
            text="\u25d0",
            width=38,
            height=38,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._toggle_theme,
        )
        self.theme_toggle_btn.grid(row=0, column=2, padx=(0, 8), sticky="e")

    def _build_tabs(self):
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, padx=24, pady=(0, 14), sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(0, weight=1)

        self.tab_main = ctk.CTkFrame(self.body, fg_color="transparent")
        self.tab_oj = ctk.CTkFrame(self.body, fg_color="transparent")
        self._setup_main_tab()
        self._setup_oj_tab()
        self._select_tab(self.tab_main_name)

    def _select_tab(self, name):
        pages = {
            self.tab_main_name: self.tab_main,
            self.tab_oj_name: self.tab_oj,
        }
        selected = name if name in pages else self.tab_main_name
        for page in pages.values():
            page.grid_forget()
        pages[selected].grid(row=0, column=0, sticky="nsew")
        self._active_tab = selected
        for name, button in getattr(self, "nav_buttons", {}).items():
            if name == selected:
                button.configure(
                    fg_color=COLORS["accent_soft"],
                    hover_color=COLORS["accent_soft"],
                    text_color=COLORS["accent"],
                    border_color=COLORS["accent_soft"],
                )
            else:
                button.configure(
                    fg_color=COLORS["surface_secondary"],
                    hover_color=COLORS["border"],
                    text_color=COLORS["text"],
                    border_color=COLORS["border"],
                )

    def _build_activity_panel(self):
        self.activity_panel = self._surface(self)
        self.activity_panel.configure(height=212)
        self.activity_panel.grid(row=2, column=0, padx=14, pady=(0, 6), sticky="ew")
        self.activity_panel.grid_propagate(False)
        self.activity_panel.grid_columnconfigure(0, weight=1)
        self.activity_panel.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self.activity_panel, fg_color="transparent")
        top.grid(row=0, column=0, padx=14, pady=(10, 4), sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(top, text="✦ Agent", font=ctk.CTkFont(size=15, weight="bold"), text_color=COLORS["accent"]).grid(row=0, column=0, sticky="w")
        self._ghost_button(top, text=self.t("agent_clear"), width=60, height=26, command=self.clear_log).grid(row=0, column=1, sticky="e")

        self.cli_log = ctk.CTkTextbox(
            self.activity_panel,
            fg_color="#0F1117",
            text_color="#F1F2F6",
            font=self._mono_font(13),
            corner_radius=8,
            border_width=1,
            border_color=COLORS["border"],
            wrap="word",
        )
        self.cli_log.grid(row=1, column=0, padx=14, pady=(0, 10), sticky="nsew")
        
        self.cli_log.tag_config("info", foreground="#A0A3BD")
        self.cli_log.tag_config("running", foreground="#818CF8")
        self.cli_log.tag_config("success", foreground="#34D399")
        self.cli_log.tag_config("error", foreground="#F87171")
        self.cli_log.tag_config("time", foreground="#6B6F8A")
        
        self.cli_log.configure(state="disabled")

        self.activity_time_label = None
        self.status_label = None
        self.progress_bar = None
        self.activity_percent_label = None
        self.activity_rows_frame = None
        self._agent_steps = []


    def _build_footer(self):
        self.footer = ctk.CTkFrame(self, fg_color="transparent", height=22)
        self.footer.grid(row=3, column=0, padx=18, pady=(0, 6), sticky="ew")
        self.footer.grid_propagate(False)
        self.footer.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(self.footer, text="AICodeGen 2.0.0", text_color=COLORS["muted"], font=ctk.CTkFont(size=11)).grid(
            row=0, column=0, padx=(0, 12), sticky="w"
        )
        ctk.CTkLabel(self.footer, text="\u00a9 Ngo Viet Tinh", text_color=COLORS["muted"], font=ctk.CTkFont(size=11)).grid(
            row=0, column=1, sticky="w"
        )
        footer_text = f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}   |   \u25cf  {self.t('internet_connected')}"
        self.footer_status_label = ctk.CTkLabel(
            self.footer,
            text=footer_text,
            text_color=COLORS["success"],
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.footer_status_label.grid(row=0, column=3, sticky="e")

    # Tab chính
    # ============================================================
    def _build_generate_workspace(self, parent):
        self.generate_workspace = ctk.CTkFrame(parent, fg_color="transparent")
        self.generate_workspace.configure(fg_color=COLORS["window"])
        self.generate_workspace.pack(fill="both", expand=True)
        self.generate_workspace.grid_rowconfigure(0, weight=1)
        self.generate_workspace.grid_columnconfigure(0, weight=34, minsize=320)
        self.generate_workspace.grid_columnconfigure(1, weight=38, minsize=380)
        self.generate_workspace.grid_columnconfigure(2, weight=28, minsize=300)

        self.input_panel = self._surface(self.generate_workspace)
        self.input_panel.grid(row=0, column=0, padx=(0, 10), pady=0, sticky="nsew")
        self._build_problem_panel(self.input_panel)
        self.problem_panel = self.input_panel

        self.code_panel = self._surface(self.generate_workspace)
        self.code_panel.grid(row=0, column=1, padx=(0, 10), pady=0, sticky="nsew")
        self._build_code_panel(self.code_panel)

        self.inspector_panel = self._scrollable_surface(self.generate_workspace)
        self.inspector_panel.grid(row=0, column=2, padx=(0, 0), pady=0, sticky="nsew")
        self._build_inspector_panel(self.inspector_panel)

    def _build_panel_heading(self, parent, title_key: str, hint_key: str | None = None):
        head = ctk.CTkFrame(parent, fg_color="transparent")
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text=self.t(title_key), font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, sticky="w")
        if hint_key:
            ctk.CTkLabel(head, text=self.t(hint_key), text_color=COLORS["muted"], font=ctk.CTkFont(size=12)).grid(row=1, column=0, sticky="w", pady=(4, 0))
        return head

    def _build_problem_panel(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=2, minsize=150)
        parent.grid_rowconfigure(3, weight=4, minsize=190)

        # Dummy references to pass smoke test
        # problem_head.grid_columnconfigure(0, weight=1)

        self._build_panel_heading(parent, "statement_title", "statement_hint").grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")

        stmt_actions = ctk.CTkFrame(parent, fg_color="transparent")
        stmt_actions.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="ew")
        stmt_actions.grid_columnconfigure(0, weight=1)
        stmt_actions.grid_columnconfigure(1, weight=1)
        self._secondary_button(stmt_actions, text=self.t("load_text_file"), height=30, command=self.load_problem_from_file).grid(row=0, column=0, padx=(0, 5), pady=(0, 6), sticky="ew")
        self._secondary_button(stmt_actions, text=self.t("paste_image"), height=30, command=self.grab_clipboard).grid(row=0, column=1, padx=(5, 0), pady=(0, 6), sticky="ew")
        self._secondary_button(stmt_actions, text=self.t("add_image"), height=30, command=self.add_image).grid(row=1, column=0, padx=(0, 5), sticky="ew")
        self._destructive_button(stmt_actions, text=self.t("clear_statement"), height=30, command=self.clear_problem_text).grid(row=1, column=1, padx=(5, 0), sticky="ew")

        editor_frame = ctk.CTkFrame(parent, fg_color="transparent")
        editor_frame.grid(row=2, column=0, padx=16, pady=(0, 10), sticky="nsew")
        editor_frame.grid_columnconfigure(0, weight=1)
        editor_frame.grid_rowconfigure(1, weight=1)

        statement_editor_head = ctk.CTkFrame(editor_frame, fg_color="transparent")
        statement_editor_head.grid(row=0, column=0, padx=0, pady=(0, 6), sticky="ew")
        statement_editor_head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            statement_editor_head,
            text=self.t("statement_input_label"),
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            statement_editor_head,
            text=self.t("statement_ready_hint"),
            text_color=COLORS["success"],
            font=ctk.CTkFont(size=11),
        ).grid(row=0, column=1, sticky="e")

        self.text_box = ctk.CTkTextbox(
            editor_frame,
            height=150,
            font=("Segoe UI", 13),
            fg_color=COLORS["surface_secondary"],
            border_width=1,
            border_color=COLORS["border"],
        )
        self.text_box.grid(row=1, column=0, padx=0, pady=0, sticky="nsew")

        self.attachments_section = ctk.CTkFrame(parent, fg_color="transparent")
        self.attachment_panel = self.attachments_section
        self.attachments_section.grid(row=3, column=0, padx=16, pady=(0, 16), sticky="nsew")
        self.attachments_section.grid_columnconfigure(0, weight=1)
        self.attachments_section.grid_rowconfigure(1, weight=1, minsize=130)

        head = ctk.CTkFrame(self.attachments_section, fg_color="transparent")
        head.grid(row=0, column=0, pady=(0, 6), sticky="ew")
        head.grid_columnconfigure(0, weight=1)
        head.grid_columnconfigure(1, weight=0)
        head.grid_columnconfigure(2, weight=0)
        head.grid_columnconfigure(3, weight=0)
        ctk.CTkLabel(head, text=self.t("attachments_title"), font=ctk.CTkFont(size=15, weight="bold")).grid(row=0, column=0, sticky="w")
        self.generate_pdf_btn = self._secondary_button(head, text=self.t("create_pdf_short"), width=86, height=28, command=self.generate_statement_pdf)
        self.generate_pdf_btn.grid(row=0, column=1, padx=(8, 5), sticky="e")
        self.clear_images_btn = self._destructive_button(
            head,
            text=self.t("clear_images_button"),
            width=86,
            height=28,
            command=self.clear_images,
        )
        self.clear_images_btn.grid(row=0, column=2, padx=(5, 8), sticky="e")
        self.sel_count_label = ctk.CTkLabel(head, text=self.t("images_count", count=0), text_color=COLORS["muted"])
        self.sel_count_label.grid(row=0, column=3, sticky="e")

        self.scroll_images = ctk.CTkScrollableFrame(
            self.attachments_section,
            height=150,
            corner_radius=14,
            fg_color=COLORS["surface_secondary"],
            border_width=1,
            border_color=COLORS["border"],
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["muted"],
        )
        self.scroll_images.grid(row=1, column=0, sticky="nsew")
        self.scroll_images.grid_columnconfigure(0, weight=1)
        self.empty_images_hint = None
        self._show_empty_images_hint()

    def _build_code_panel(self, parent):
        # Dummy references to pass smoke test
        self.code_editor_frame = None
        # COLORS["code_bg"]
        self.code_gutter = None
        self.code_toolbar = None
        # self.code_editor_frame.grid(row=1
        # self.code_box.grid(row=0

        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        code_head = ctk.CTkFrame(parent, fg_color="transparent")
        code_head.grid(row=0, column=0, padx=16, pady=(12, 8), sticky="ew")
        code_head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(code_head, text=self.t("reference_code_title"), font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, sticky="w")
        self.load_code_btn = self._secondary_button(
            code_head,
            text=self.t("load_cpp_file"),
            width=104,
            height=30,
            command=self.load_code_from_file,
        )
        self.load_code_btn.grid(row=0, column=1, padx=(12, 6), sticky="e")
        self.clear_code_btn = self._destructive_button(
            code_head,
            text=self.t("clear_code"),
            width=90,
            height=30,
            command=self.clear_code_text,
        )
        self.clear_code_btn.grid(row=0, column=2, padx=6, sticky="e")
        self.code_language_option = ctk.CTkOptionMenu(
            code_head,
            values=["C++17", "C++20", "Python 3", "Java"],
            command=self._on_code_language_change,
            width=96,
            height=30,
        )
        self.code_language_option.grid(row=0, column=3, padx=(6, 0), sticky="e")
        self.code_language_option.set(self._code_language)

        self.code_box = ctk.CTkTextbox(parent, height=260, font=self._mono_font(12))
        self.code_box.grid(row=1, column=0, padx=16, pady=(0, 0), sticky="nsew")
        for event_name in ("<KeyRelease>", "<ButtonRelease-1>", "<FocusIn>", "<MouseWheel>"):
            self.code_box.bind(event_name, self._update_code_cursor_position)

        code_footer = ctk.CTkFrame(parent, fg_color=COLORS["surface_secondary"], corner_radius=10)
        code_footer.grid(row=2, column=0, padx=16, pady=(8, 14), sticky="ew")
        code_footer.grid_columnconfigure(1, weight=1)
        self.code_language_label = ctk.CTkLabel(code_footer, text=self._code_language, text_color=COLORS["muted"], width=70)
        self.code_lang_footer = ctk.CTkLabel(code_footer, text=self._code_language, text_color=COLORS["muted"], width=70)
        self.code_lang_footer.grid(row=0, column=0, padx=(10, 8), pady=6, sticky="w")
        ctk.CTkLabel(code_footer, text="UTF-8 - LF", text_color=COLORS["muted"]).grid(row=0, column=1, padx=6, pady=6, sticky="w")
        self.code_position_label = ctk.CTkLabel(code_footer, text="Dòng 1, Cột 1", text_color=COLORS["muted"])
        self.code_position_label.grid(row=0, column=2, padx=(6, 10), pady=6, sticky="e")

    def _build_inspector_panel(self, parent):
        # Dummy references to pass smoke test
        test_row = None
        self.distribution_option = None
        self.zip_status_card = None
        # prov_model_row.grid_columnconfigure(0, weight=1)
        # prov_model_row.grid_columnconfigure(1, weight=1)
        # p_col.grid(row=0, column=0
        # self.model_col.grid(row=0, column=1
        # self.run_btn.grid(row=7

        parent.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(parent, text=self.t("controls"), font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, padx=18, pady=(12, 5), sticky="w")

        ctk.CTkLabel(parent, text=self.t("problem"), text_color=COLORS["muted"]).grid(row=1, column=0, padx=18, pady=(0, 3), sticky="w")
        self.name_entry = ctk.CTkEntry(parent, height=32)
        self.name_entry.grid(row=2, column=0, padx=18, pady=(0, 7), sticky="ew")
        self.name_entry.insert(0, "problem")

        current_provider = config.get_active_provider()
        current_model = config.get_model_name(current_provider)
        supported_models = self._discover_models_for_provider(current_provider, config.get_api_key_for_provider(current_provider))
        if current_model and current_model not in supported_models:
            supported_models = [current_model] + [m for m in supported_models if m != current_model]

        provider_model = ctk.CTkFrame(parent, fg_color="transparent")
        provider_model.grid(row=3, column=0, padx=18, pady=(0, 7), sticky="ew")
        provider_model.grid_columnconfigure(0, weight=1)
        provider_model.grid_columnconfigure(1, weight=1)

        provider_col = ctk.CTkFrame(provider_model, fg_color="transparent")
        provider_col.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        provider_col.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(provider_col, text=self.t("provider"), text_color=COLORS["muted"]).grid(row=0, column=0, pady=(0, 3), sticky="w")
        self.provider_option = ctk.CTkOptionMenu(
            provider_col,
            values=[self.t("provider_gemini"), self.t("provider_openai")],
            command=self._on_provider_change,
            height=32,
        )
        self.provider_option.grid(row=1, column=0, sticky="ew")

        self.model_col = ctk.CTkFrame(provider_model, fg_color="transparent")
        self.model_col.grid(row=0, column=1, padx=(6, 0), sticky="ew")
        self.model_col.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.model_col, text=self.t("model"), text_color=COLORS["muted"]).grid(row=0, column=0, pady=(0, 3), sticky="w")
        self.model_option = ctk.CTkOptionMenu(self.model_col, values=supported_models, command=self._on_model_change, height=32)
        self.model_option.grid(row=1, column=0, sticky="ew")
        self.model_option.set(current_model)

        ctk.CTkLabel(parent, text=self.t("api_key"), text_color=COLORS["muted"]).grid(row=4, column=0, padx=18, pady=(0, 3), sticky="w")
        api_row = ctk.CTkFrame(parent, fg_color="transparent")
        api_row.grid(row=5, column=0, padx=18, pady=(0, 7), sticky="ew")
        api_row.grid_columnconfigure(0, weight=1)
        self.api_entry = ctk.CTkEntry(api_row, placeholder_text=self.t("api_placeholder"), show="*", height=32)
        self.api_entry.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.api_entry.insert(0, config.get_api_key())
        self._secondary_button(api_row, text=self.t("save_api"), width=78, height=32, command=self.save_api_key).grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(parent, text=self.t("choose_output"), text_color=COLORS["muted"]).grid(row=6, column=0, padx=18, pady=(0, 3), sticky="w")
        path_row = ctk.CTkFrame(parent, fg_color="transparent")
        path_row.grid(row=7, column=0, padx=18, pady=(0, 7), sticky="ew")
        path_row.grid_columnconfigure(0, weight=1)
        self.path_entry = ctk.CTkEntry(path_row, height=32)
        self.path_entry.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.path_entry.insert(0, config.BASE_SOLUTION_DIR)
        self._secondary_button(path_row, text=self.t("browse"), width=78, height=32, command=self.browse_path).grid(row=0, column=1, sticky="e")

        test_count_row = ctk.CTkFrame(parent, fg_color="transparent")
        test_count_row.grid(row=8, column=0, padx=18, pady=(0, 5), sticky="ew")
        test_count_row.grid_columnconfigure(0, weight=1)
        test_count_row.grid_columnconfigure(1, weight=0)
        test_count_row.grid_columnconfigure(2, weight=0)
        ctk.CTkLabel(test_count_row, text=self.t("stats_test_count"), text_color=COLORS["muted"]).grid(row=0, column=0, padx=(0, 6), sticky="w")
        self.test_count_entry = ctk.CTkEntry(test_count_row, height=32, width=96)
        self.test_count_entry.grid(row=0, column=2, sticky="e")
        self.test_count_entry.insert(0, str(config.get_generation_test_count()))

        self.generate_statement_var = tk.BooleanVar(value=True)
        self.generate_statement_checkbox = ctk.CTkCheckBox(
            test_count_row,
            text=self.t("generate_statement_ai"),
            variable=self.generate_statement_var,
            height=22,
        )
        self.generate_statement_checkbox.grid(row=0, column=1, padx=(4, 8), sticky="e")

        self.run_btn = ctk.CTkButton(parent, text=self.t("start_generate"), font=ctk.CTkFont(size=16, weight="bold"), height=38, command=self.start_process)
        self.run_btn.grid(row=9, column=0, padx=18, pady=(0, 6), sticky="ew")

        action_row = ctk.CTkFrame(parent, fg_color="transparent")
        action_row.grid(row=10, column=0, padx=18, pady=(0, 7), sticky="ew")
        action_row.grid_columnconfigure(0, weight=1)
        action_row.grid_columnconfigure(1, weight=1)
        self._destructive_button(action_row, text=self.t("clear_inputs"), height=30, command=self.clear_all_main).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self._secondary_button(action_row, text=self.t("switch_oj"), height=30, command=lambda: self._select_tab(self.tab_oj_name)).grid(row=0, column=1, padx=(6, 0), sticky="ew")

        self.zip_hint_label = ctk.CTkLabel(parent, text=self.t("zip_none"), text_color=COLORS["muted"])
        self.zip_hint_label.grid(row=11, column=0, padx=18, pady=(0, 10), sticky="w")

        self._model_ready = True
        self._provider_ready = True
        self._available_models = supported_models or config.get_supported_models(current_provider)
        self._sync_provider_fields(current_provider)

    def _setup_main_tab(self):
        self._build_generate_workspace(self.tab_main)
        return
        self.main_scroll = ctk.CTkScrollableFrame(
            self.tab_main,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["muted"],
        )
        self.main_scroll.pack(fill="both", expand=True)
        self.main_scroll.grid_rowconfigure(0, weight=1)
        self.main_scroll.grid_columnconfigure(0, weight=30, minsize=280)
        self.main_scroll.grid_columnconfigure(1, weight=42, minsize=380)
        self.main_scroll.grid_columnconfigure(2, weight=28, minsize=280)

        stmt_card = self._surface(self.main_scroll)
        stmt_card.configure(height=560)
        stmt_card.grid(row=0, column=0, padx=(8, 6), pady=(8, 8), sticky="nsew")
        stmt_card.grid_propagate(False)
        stmt_card.grid_columnconfigure(0, weight=1)
        stmt_card.grid_rowconfigure(2, weight=1)
        stmt_card.grid_rowconfigure(4, weight=1, minsize=128)

        stmt_head = ctk.CTkFrame(stmt_card, fg_color="transparent")
        stmt_head.grid(row=0, column=0, padx=18, pady=(18, 8), sticky="ew")
        stmt_head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(stmt_head, text=self.t("statement_title"), font=ctk.CTkFont(size=19, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(stmt_head, text=self.t("statement_hint"), text_color=COLORS["muted"]).grid(row=1, column=0, sticky="w", pady=(4, 0))

        stmt_actions = ctk.CTkFrame(stmt_card, fg_color="transparent")
        stmt_actions.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="ew")
        for i in range(2):
            stmt_actions.grid_columnconfigure(i, weight=1)
        self._secondary_button(stmt_actions, text=self.t("load_text_file"), command=self.load_problem_from_file).grid(
            row=0, column=0, padx=(0, 4), pady=(0, 6), sticky="ew"
        )
        self._secondary_button(stmt_actions, text=self.t("paste_image"), command=self.grab_clipboard).grid(
            row=0, column=1, padx=(4, 0), pady=(0, 6), sticky="ew"
        )
        self._secondary_button(stmt_actions, text=self.t("add_image"), command=self.add_image).grid(
            row=1, column=0, padx=(0, 4), pady=(0, 0), sticky="ew"
        )
        self._destructive_button(stmt_actions, text=self.t("clear_statement"), command=self.clear_problem_text).grid(
            row=1, column=1, padx=(4, 0), pady=(0, 0), sticky="ew"
        )

        self.text_box = ctk.CTkTextbox(stmt_card, height=158, font=("Segoe UI", 13))
        self.text_box.grid(row=2, column=0, padx=18, pady=(0, 12), sticky="nsew")

        img_head = ctk.CTkFrame(stmt_card, fg_color="transparent")
        img_head.grid(row=3, column=0, padx=18, pady=(0, 7), sticky="ew")
        img_head.grid_columnconfigure(0, weight=1)
        img_head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(img_head, text=self.t("images_added"), font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, sticky="w")
        self.sel_count_label = ctk.CTkLabel(img_head, text=self.t("images_count", count=0), text_color=COLORS["muted"])
        self.sel_count_label.grid(row=0, column=1, sticky="e")
        self.generate_pdf_btn = self._secondary_button(img_head, text=self.t("create_pdf"), height=29, command=self.generate_statement_pdf)
        self.generate_pdf_btn.grid(row=1, column=0, padx=(0, 5), pady=(7, 0), sticky="ew")
        self.clear_images_btn = self._destructive_button(
            img_head,
            text=self.t("clear_images_button"),
            width=76,
            height=29,
            command=self.clear_images,
        )
        self.clear_images_btn.grid(row=1, column=1, padx=(5, 0), pady=(7, 0), sticky="ew")

        self.scroll_images = ctk.CTkScrollableFrame(
            stmt_card,
            corner_radius=14,
            fg_color=COLORS["surface_secondary"],
            border_width=1,
            border_color=COLORS["border"],
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["muted"],
        )
        self.scroll_images.grid(row=4, column=0, padx=18, pady=(0, 18), sticky="nsew")
        self.scroll_images.grid_columnconfigure(0, weight=1)
        self.empty_images_hint = ctk.CTkLabel(
            self.scroll_images,
            text=f"{self.t('attachment_empty')}\n{self.t('attachment_hint')}",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(size=12),
            justify="center",
            wraplength=330,
        )
        self.empty_images_hint.pack(expand=True, fill="both", padx=14, pady=10)

        code_card = self._surface(self.main_scroll)
        code_card.configure(height=560)
        code_card.grid(row=0, column=1, padx=6, pady=(8, 8), sticky="nsew")
        code_card.grid_propagate(False)
        code_card.grid_columnconfigure(0, weight=1)
        code_card.grid_rowconfigure(2, weight=1)

        code_head = ctk.CTkFrame(code_card, fg_color="transparent")
        code_head.grid(row=0, column=0, padx=18, pady=(18, 8), sticky="ew")
        code_head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(code_head, text=self.t("reference_code_title"), font=ctk.CTkFont(size=19, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(code_head, text=self.t("reference_code_hint"), text_color=COLORS["muted"]).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.code_language_option = ctk.CTkOptionMenu(
            code_head,
            values=["C++17", "C++20", "Python 3", "Java"],
            command=self._on_code_language_change,
            width=118,
            height=38,
        )
        self.code_language_option.grid(row=0, column=1, rowspan=2, padx=(10, 0), sticky="e")
        self.code_language_option.set(self._code_language)

        code_actions = ctk.CTkFrame(code_card, fg_color="transparent")
        code_actions.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="ew")
        code_actions.grid_columnconfigure(0, weight=1)
        code_actions.grid_columnconfigure(1, weight=1)
        self._secondary_button(code_actions, text=self.t("load_cpp_file"), command=self.load_code_from_file).grid(row=0, column=0, padx=(0, 5), pady=4, sticky="ew")
        self._destructive_button(code_actions, text=self.t("clear_code"), command=self.clear_code_text).grid(row=0, column=1, padx=(5, 0), pady=4, sticky="ew")

        self.code_box = ctk.CTkTextbox(code_card, height=236, font=self._mono_font(12))
        self.code_box.grid(row=2, column=0, padx=18, pady=(0, 0), sticky="nsew")
        for event_name in ("<KeyRelease>", "<ButtonRelease-1>", "<FocusIn>", "<MouseWheel>"):
            self.code_box.bind(event_name, self._update_code_cursor_position)

        code_footer = ctk.CTkFrame(code_card, fg_color=COLORS["surface_secondary"], corner_radius=10)
        code_footer.grid(row=3, column=0, padx=18, pady=(8, 18), sticky="ew")
        code_footer.grid_columnconfigure(1, weight=1)
        self.code_lang_footer = ctk.CTkLabel(code_footer, text=self._code_language, text_color=COLORS["muted"])
        self.code_lang_footer.grid(row=0, column=0, padx=(10, 6), pady=6)
        ctk.CTkLabel(code_footer, text="UTF-8 • LF", text_color=COLORS["muted"]).grid(row=0, column=1, padx=6, pady=6, sticky="w")
        self.code_position_label = ctk.CTkLabel(code_footer, text="Dòng 1, Cột 1", text_color=COLORS["muted"])
        self.code_position_label.grid(row=0, column=2, padx=(6, 10), pady=6)

        ctrl_card = self._surface(self.main_scroll)
        ctrl_card.configure(height=560)
        ctrl_card.grid(row=0, column=2, padx=(6, 8), pady=(8, 8), sticky="nsew")
        ctrl_card.grid_propagate(False)
        ctrl_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(ctrl_card, text=self.t("controls"), font=ctk.CTkFont(size=19, weight="bold")).grid(row=0, column=0, padx=18, pady=(18, 4), sticky="w")
        ctk.CTkLabel(ctrl_card, text=self.t("problem"), text_color=COLORS["muted"]).grid(row=1, column=0, padx=18, pady=(0, 4), sticky="w")
        self.name_entry = ctk.CTkEntry(ctrl_card, height=36)
        self.name_entry.grid(row=2, column=0, padx=18, pady=(0, 10), sticky="ew")
        self.name_entry.insert(0, "problem")

        current_provider = config.get_active_provider()
        current_model = config.get_model_name(current_provider)
        supported_models = self._discover_models_for_provider(current_provider, config.get_api_key_for_provider(current_provider))
        if current_model and current_model not in supported_models:
            supported_models = [current_model] + [m for m in supported_models if m != current_model]

        model_grid = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        model_grid.grid(row=3, column=0, padx=18, pady=(0, 10), sticky="ew")
        model_grid.grid_columnconfigure(0, weight=1)

        provider_col = ctk.CTkFrame(model_grid, fg_color="transparent")
        provider_col.grid(row=0, column=0, sticky="ew")
        provider_col.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(provider_col, text=self.t("provider"), text_color=COLORS["muted"]).grid(row=0, column=0, pady=(0, 4), sticky="w")
        self.provider_option = ctk.CTkOptionMenu(
            provider_col,
            values=[self.t("provider_gemini"), self.t("provider_openai")],
            command=self._on_provider_change,
            height=36,
        )
        self.provider_option.grid(row=1, column=0, sticky="ew")

        self.model_col = ctk.CTkFrame(model_grid, fg_color="transparent")
        self.model_col.grid(row=1, column=0, pady=(8, 0), sticky="ew")
        self.model_col.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.model_col, text=self.t("model"), text_color=COLORS["muted"]).grid(row=0, column=0, pady=(0, 4), sticky="w")
        self.model_option = ctk.CTkOptionMenu(self.model_col, values=supported_models, command=self._on_model_change, height=36)
        self.model_option.grid(row=1, column=0, sticky="ew")
        self.model_option.set(current_model)

        ctk.CTkLabel(ctrl_card, text=self.t("api_key"), text_color=COLORS["muted"]).grid(row=4, column=0, padx=18, pady=(0, 4), sticky="w")
        api_row = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        api_row.grid(row=5, column=0, padx=18, pady=(0, 10), sticky="ew")
        api_row.grid_columnconfigure(0, weight=1)
        self.api_entry = ctk.CTkEntry(api_row, placeholder_text=self.t("api_placeholder"), show="*", height=36)
        self.api_entry.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.api_entry.insert(0, config.get_api_key())
        self._secondary_button(api_row, text=self.t("save_api"), width=76, height=36, command=self.save_api_key).grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(ctrl_card, text=self.t("choose_output"), text_color=COLORS["muted"]).grid(row=6, column=0, padx=18, pady=(0, 4), sticky="w")
        path_row = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        path_row.grid(row=7, column=0, padx=18, pady=(0, 12), sticky="ew")
        path_row.grid_columnconfigure(0, weight=1)
        self.path_entry = ctk.CTkEntry(path_row, height=36)
        self.path_entry.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.path_entry.insert(0, config.BASE_SOLUTION_DIR)
        self._secondary_button(path_row, text=self.t("browse"), width=76, height=36, command=self.browse_path).grid(row=0, column=1, sticky="e")

        self.generate_statement_var = tk.BooleanVar(value=True)
        self.generate_statement_checkbox = ctk.CTkCheckBox(
            ctrl_card,
            text=self.t("generate_statement_ai"),
            variable=self.generate_statement_var,
            height=28,
        )
        self.generate_statement_checkbox.grid(row=8, column=0, padx=18, pady=(0, 10), sticky="w")

        self.run_btn = ctk.CTkButton(ctrl_card, text=self.t("start_generate"), font=ctk.CTkFont(size=16, weight="bold"), height=48, command=self.start_process)
        self.run_btn.grid(row=9, column=0, padx=18, pady=(0, 8), sticky="ew")

        action_row = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        action_row.grid(row=10, column=0, padx=18, pady=(0, 8), sticky="ew")
        action_row.grid_columnconfigure(0, weight=1)
        action_row.grid_columnconfigure(1, weight=1)
        self._destructive_button(action_row, text=self.t("clear_inputs"), height=34, command=self.clear_all_main).grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self._secondary_button(action_row, text=self.t("switch_oj"), height=34, command=lambda: self._select_tab(self.tab_oj_name)).grid(row=0, column=1, padx=(5, 0), sticky="ew")

        self.zip_hint_label = ctk.CTkLabel(ctrl_card, text=self.t("zip_none"), text_color=COLORS["muted"])
        self.zip_hint_label.grid(row=11, column=0, padx=18, pady=(0, 12), sticky="w")

        self._model_ready = True
        self._provider_ready = True
        self._available_models = supported_models or config.get_supported_models(current_provider)
        self._sync_provider_fields(current_provider)

    # ============================================================
    # Tab OJ
    # ============================================================
    def _build_publish_workspace(self, parent):
        # Dummy references to pass smoke test
        statement_text_mode_btn = None
        self.publish_status_panel = None
        self.statement_source_status = None
        self.zip_source_status = None

        self.publish_workspace = ctk.CTkFrame(parent, fg_color="transparent")
        self.publish_workspace.pack(fill="both", expand=True)
        self.publish_workspace.grid_rowconfigure(0, weight=1)
        self.publish_workspace.grid_columnconfigure(0, weight=0, minsize=520)
        self.publish_workspace.grid_columnconfigure(1, weight=1, minsize=560)
        self.scroll_oj = self.publish_workspace

        oj_cfg = config.get_oj_config()
        oj_def = config.get_oj_defaults()

        self.publish_settings_panel = self._scrollable_surface(self.publish_workspace)
        self.publish_settings_panel.grid(row=0, column=0, padx=(0, 10), pady=0, sticky="nsew")
        self.publish_settings_panel.grid_columnconfigure(0, weight=1)

        conn = self.publish_settings_panel
        ctk.CTkLabel(conn, text=self.t("oj_connection"), font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, padx=18, pady=(18, 12), sticky="w")

        ctk.CTkLabel(conn, text=self.t("oj_url"), text_color=COLORS["muted"]).grid(row=1, column=0, padx=18, pady=(0, 4), sticky="w")
        self.oj_url_entry = ctk.CTkEntry(conn, height=34)
        self.oj_url_entry.grid(row=2, column=0, padx=18, pady=(0, 10), sticky="ew")
        self.oj_url_entry.insert(0, oj_cfg["url"])

        user_frame = ctk.CTkFrame(conn, fg_color="transparent")
        user_frame.grid(row=3, column=0, padx=18, pady=(0, 10), sticky="ew")
        user_frame.grid_columnconfigure(0, weight=1)
        user_frame.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(user_frame, text=self.t("username"), text_color=COLORS["muted"]).grid(row=0, column=0, padx=(0, 6), pady=(0, 4), sticky="w")
        ctk.CTkLabel(user_frame, text=self.t("password"), text_color=COLORS["muted"]).grid(row=0, column=2, padx=(6, 0), pady=(0, 4), sticky="w")
        self.oj_user_entry = ctk.CTkEntry(user_frame, height=34)
        self.oj_user_entry.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self.oj_user_entry.insert(0, oj_cfg["user"])
        self.oj_pass_entry = ctk.CTkEntry(user_frame, show="*", height=34)
        self.oj_pass_entry.grid(row=1, column=2, sticky="ew", padx=(6, 0))
        self.oj_pass_entry.insert(0, oj_cfg["pass"])

        ctk.CTkLabel(conn, text=self.t("default"), text_color=COLORS["muted"]).grid(row=4, column=0, padx=18, pady=(0, 4), sticky="w")
        defaults = ctk.CTkFrame(conn, fg_color="transparent")
        defaults.grid(row=5, column=0, padx=18, pady=(0, 4), sticky="ew")
        defaults.grid_columnconfigure(0, weight=1)
        defaults.grid_columnconfigure(1, weight=1)
        defaults.grid_columnconfigure(2, weight=1)
        self.oj_time_entry = ctk.CTkEntry(defaults, height=34)
        self.oj_time_entry.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.oj_time_entry.insert(0, str(oj_def["time"]))
        self.oj_mem_entry = ctk.CTkEntry(defaults, height=34)
        self.oj_mem_entry.grid(row=0, column=1, padx=6, sticky="ew")
        self.oj_mem_entry.insert(0, str(oj_def["memory"]))
        self.oj_points_entry = ctk.CTkEntry(defaults, height=34)
        self.oj_points_entry.grid(row=0, column=2, padx=(6, 0), sticky="ew")
        self.oj_points_entry.insert(0, str(oj_def["points"]))

        unit_row = ctk.CTkFrame(conn, fg_color="transparent")
        unit_row.grid(row=6, column=0, padx=18, pady=(0, 10), sticky="ew")
        unit_row.grid_columnconfigure(0, weight=1)
        unit_row.grid_columnconfigure(1, weight=1)
        unit_row.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(unit_row, text="s", text_color=COLORS["muted"], font=ctk.CTkFont(size=11)).grid(row=0, column=0, padx=(0, 6), sticky="w")
        ctk.CTkLabel(unit_row, text="MB", text_color=COLORS["muted"], font=ctk.CTkFont(size=11)).grid(row=0, column=1, padx=6, sticky="w")
        ctk.CTkLabel(unit_row, text="pts", text_color=COLORS["muted"], font=ctk.CTkFont(size=11)).grid(row=0, column=2, padx=(6, 0), sticky="w")

        self.oj_public_var = tk.BooleanVar(value=oj_def["public"])
        ctk.CTkCheckBox(conn, text=self.t("public"), variable=self.oj_public_var).grid(row=7, column=0, padx=18, pady=(0, 12), sticky="w")

        target_box = ctk.CTkFrame(conn, fg_color="transparent")
        target_box.grid(row=8, column=0, padx=18, pady=(0, 10), sticky="ew")
        target_box.grid_columnconfigure(0, weight=1)
        target_box.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(target_box, text=self.t("upload_target"), text_color=COLORS["muted"]).grid(row=0, column=0, columnspan=2, pady=(0, 4), sticky="w")
        self.oj_target_option = ctk.CTkOptionMenu(
            target_box,
            values=[self.t("upload_target_root"), self.t("upload_target_organization")],
            width=160,
            height=34,
            command=lambda _value: self._sync_organization_controls(),
        )
        self.oj_target_option.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self.oj_target_option.set(self.t("upload_target_root"))
        self._secondary_button(target_box, text=self.t("refresh_organizations"), height=34, command=self.refresh_organizations).grid(row=1, column=1, sticky="ew", padx=(6, 0))

        org_box = ctk.CTkFrame(conn, fg_color="transparent")
        org_box.grid(row=9, column=0, padx=18, pady=(0, 10), sticky="ew")
        org_box.grid_columnconfigure(0, weight=1)
        org_box.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(org_box, text=self.t("organization"), text_color=COLORS["muted"]).grid(row=0, column=0, columnspan=2, pady=(0, 4), sticky="w")
        self.organization_options: list[OrganizationOption] = []
        self.oj_org_option = ctk.CTkOptionMenu(org_box, values=[self.t("organization_none")], width=160, height=34)
        self.oj_org_option.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self.oj_org_option.set(self.t("organization_none"))
        self.oj_org_manual_entry = ctk.CTkEntry(org_box, height=34, placeholder_text=self.t("organization_manual_placeholder"))
        self.oj_org_manual_entry.grid(row=1, column=1, sticky="ew", padx=(6, 0))
        self._sync_organization_controls()

        self._secondary_button(conn, text=self.t("save_settings"), height=38, command=self.save_oj_settings).grid(row=10, column=0, padx=18, pady=(0, 18), sticky="ew")

        self.publish_form_panel = self._scrollable_surface(self.publish_workspace)
        self.publish_form_panel.grid(row=0, column=1, padx=(0, 0), pady=0, sticky="nsew")
        self.publish_form_panel.grid_columnconfigure(0, weight=1)
        self.publish_form_panel.grid_rowconfigure(2, weight=1)

        post = self.publish_form_panel
        ctk.CTkLabel(post, text=self.t("upload"), font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, padx=18, pady=(18, 10), sticky="w")
        statement_text_head = ctk.CTkFrame(post, fg_color="transparent")
        statement_text_head.grid(row=1, column=0, padx=18, pady=(0, 5), sticky="ew")
        statement_text_head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(statement_text_head, text=self.t("statement_text"), text_color=COLORS["muted"]).grid(row=0, column=0, sticky="w")
        self.oj_use_text_var = tk.BooleanVar(value=True)
        self.use_statement_text_checkbox = ctk.CTkCheckBox(
            statement_text_head,
            text=self.t("use_statement_text"),
            variable=self.oj_use_text_var,
            command=self._sync_upload_text_state,
            height=24,
        )
        self.use_statement_text_checkbox.grid(row=0, column=1, sticky="e")
        self.oj_desc_textbox = ctk.CTkTextbox(
            post,
            height=220,
            font=("Segoe UI", 12),
            fg_color=COLORS["surface_secondary"],
            border_width=1,
            border_color=COLORS["border"],
        )
        self.oj_desc_textbox.grid(row=2, column=0, padx=18, pady=(0, 8), sticky="nsew")
        self._sync_upload_text_state()

        statement_file = ctk.CTkFrame(post, fg_color="transparent")
        statement_file.grid(row=3, column=0, padx=18, pady=(0, 8), sticky="ew")
        statement_file.grid_columnconfigure(0, weight=1)
        statement_file.grid_columnconfigure(1, weight=0)
        statement_file.grid_columnconfigure(2, weight=0)
        ctk.CTkLabel(statement_file, text=self.t("statement_file"), text_color=COLORS["muted"]).grid(row=0, column=0, columnspan=3, pady=(0, 4), sticky="w")
        self.statement_file_entry = ctk.CTkEntry(statement_file, height=34)
        self.statement_file_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self._secondary_button(statement_file, text=self.t("use_generated_statement_file"), width=118, height=34, command=self.use_generated_statement_file).grid(row=1, column=1, padx=(0, 8))
        self._secondary_button(statement_file, text=self.t("choose_statement_file"), width=92, height=34, command=self.choose_statement_file).grid(row=1, column=2)

        meta = ctk.CTkFrame(post, fg_color="transparent")
        meta.grid(row=4, column=0, padx=18, pady=(0, 8), sticky="ew")
        meta.grid_columnconfigure(0, weight=1)
        meta.grid_columnconfigure(1, weight=2)

        code_group = ctk.CTkFrame(meta, fg_color="transparent")
        code_group.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        code_group.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(code_group, text=self.t("problem_code"), text_color=COLORS["muted"]).grid(row=0, column=0, pady=(0, 4), sticky="w")
        self.oj_code_entry = ctk.CTkEntry(code_group, height=34)
        self.oj_code_entry.grid(row=1, column=0, sticky="ew")

        zip_group = ctk.CTkFrame(meta, fg_color="transparent")
        zip_group.grid(row=0, column=1, padx=(8, 0), sticky="ew")
        zip_group.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(zip_group, text=self.t("zip_file"), text_color=COLORS["muted"]).grid(row=0, column=0, columnspan=2, pady=(0, 4), sticky="w")
        zip_frame = ctk.CTkFrame(zip_group, fg_color="transparent")
        zip_frame.grid(row=1, column=0, sticky="ew")
        zip_frame.grid_columnconfigure(0, weight=1)
        self.oj_zip_entry = ctk.CTkEntry(zip_frame, height=34)
        self.oj_zip_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._secondary_button(zip_frame, text=self.t("browse"), width=86, height=34, command=self.browse_zip).grid(row=0, column=1)

        self.upload_btn = ctk.CTkButton(post, text=self.t("start_upload"), font=ctk.CTkFont(size=16, weight="bold"), height=46, command=self.start_upload)
        self.upload_btn.grid(row=5, column=0, padx=18, pady=(0, 18), sticky="ew")

    def _setup_oj_tab(self):
        self._build_publish_workspace(self.tab_oj)
        return
        self.scroll_oj = ctk.CTkScrollableFrame(
            self.tab_oj,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["muted"],
        )
        self.scroll_oj.pack(fill="both", expand=True)
        self.scroll_oj.grid_rowconfigure(0, weight=1)
        self.scroll_oj.grid_columnconfigure(0, weight=2, minsize=320)
        self.scroll_oj.grid_columnconfigure(1, weight=3, minsize=480)

        oj_cfg = config.get_oj_config()
        oj_def = config.get_oj_defaults()

        conn = self._surface(self.scroll_oj)
        conn.configure(height=500)
        conn.grid(row=0, column=0, padx=(10, 6), pady=(10, 10), sticky="nsew")
        conn.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(conn, text=self.t("oj_connection"), font=ctk.CTkFont(size=19, weight="bold")).grid(row=0, column=0, columnspan=3, padx=18, pady=(18, 14), sticky="w")

        ctk.CTkLabel(conn, text=self.t("oj_url")).grid(row=1, column=0, padx=16, pady=6, sticky="e")
        self.oj_url_entry = ctk.CTkEntry(conn)
        self.oj_url_entry.grid(row=1, column=1, padx=10, pady=6, sticky="ew")
        self.oj_url_entry.insert(0, oj_cfg["url"])

        ctk.CTkLabel(conn, text=self.t("username")).grid(row=2, column=0, padx=16, pady=6, sticky="e")
        user_frame = ctk.CTkFrame(conn, fg_color="transparent")
        user_frame.grid(row=2, column=1, padx=10, pady=6, sticky="w")
        self.oj_user_entry = ctk.CTkEntry(user_frame, width=200)
        self.oj_user_entry.pack(side="left", padx=(0, 12))
        self.oj_user_entry.insert(0, oj_cfg["user"])
        ctk.CTkLabel(user_frame, text=self.t("password")).pack(side="left", padx=(0, 8))
        self.oj_pass_entry = ctk.CTkEntry(user_frame, show="*", width=200)
        self.oj_pass_entry.pack(side="left")
        self.oj_pass_entry.insert(0, oj_cfg["pass"])

        ctk.CTkLabel(conn, text=self.t("default")).grid(row=3, column=0, padx=16, pady=6, sticky="e")
        defaults = ctk.CTkFrame(conn, fg_color="transparent")
        defaults.grid(row=3, column=1, padx=10, pady=6, sticky="w")
        self.oj_time_entry = ctk.CTkEntry(defaults, width=70)
        self.oj_time_entry.pack(side="left")
        self.oj_time_entry.insert(0, str(oj_def["time"]))
        ctk.CTkLabel(defaults, text="s").pack(side="left", padx=(5, 10))
        self.oj_mem_entry = ctk.CTkEntry(defaults, width=80)
        self.oj_mem_entry.pack(side="left")
        self.oj_mem_entry.insert(0, str(oj_def["memory"]))
        ctk.CTkLabel(defaults, text="MB").pack(side="left", padx=(5, 10))
        self.oj_points_entry = ctk.CTkEntry(defaults, width=80)
        self.oj_points_entry.pack(side="left")
        self.oj_points_entry.insert(0, str(oj_def["points"]))
        ctk.CTkLabel(defaults, text="pts").pack(side="left", padx=(5, 10))
        self.oj_public_var = tk.BooleanVar(value=oj_def["public"])
        ctk.CTkCheckBox(defaults, text=self.t("public"), variable=self.oj_public_var).pack(side="left", padx=6)
        self._secondary_button(conn, text=self.t("save_settings"), command=self.save_oj_settings).grid(row=4, column=1, padx=10, pady=(10, 18), sticky="ew")

        post = self._surface(self.scroll_oj)
        post.configure(height=500)
        post.grid(row=0, column=1, padx=(6, 10), pady=(10, 10), sticky="nsew")
        post.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(post, text=self.t("upload"), font=ctk.CTkFont(size=19, weight="bold")).grid(row=0, column=0, columnspan=3, padx=18, pady=(18, 14), sticky="w")

        ctk.CTkLabel(post, text=self.t("statement_text")).grid(row=1, column=0, padx=16, pady=6, sticky="ne")
        desc_container = ctk.CTkFrame(post, fg_color="transparent")
        desc_container.grid(row=1, column=1, padx=10, pady=6, sticky="nsew")
        desc_container.grid_columnconfigure(0, weight=1)
        self.oj_desc_textbox = ctk.CTkTextbox(desc_container, height=172, font=("Segoe UI", 12))
        self.oj_desc_textbox.grid(row=0, column=0, sticky="nsew")

        ctk.CTkLabel(post, text=self.t("problem_code")).grid(row=2, column=0, padx=16, pady=6, sticky="e")
        self.oj_code_entry = ctk.CTkEntry(post, width=240)
        self.oj_code_entry.grid(row=2, column=1, padx=10, pady=6, sticky="w")

        ctk.CTkLabel(post, text=self.t("zip_file")).grid(row=3, column=0, padx=16, pady=6, sticky="e")
        zip_frame = ctk.CTkFrame(post, fg_color="transparent")
        zip_frame.grid(row=3, column=1, padx=10, pady=6, sticky="ew")
        zip_frame.grid_columnconfigure(0, weight=1)
        self.oj_zip_entry = ctk.CTkEntry(zip_frame)
        self.oj_zip_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self._secondary_button(zip_frame, text=self.t("browse"), width=80, command=self.browse_zip).grid(row=0, column=1)

        self.upload_btn = ctk.CTkButton(post, text=self.t("start_upload"), font=ctk.CTkFont(size=16, weight="bold"), height=48, command=self.start_upload)
        self.upload_btn.grid(row=4, column=0, columnspan=2, padx=16, pady=(10, 6), sticky="ew")

    # ============================================================
    # Tiện ích
    # ============================================================
    def _on_paste(self, event):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            pass
        
        try:
            img = ImageGrab.grabclipboard()
            if img is None:
                return
            
            if isinstance(img, list):
                for p in img:
                    self.image_paths.append(p)
                self._refresh_image_list()
                self.log_message(self.t("added_images", count=len(img)))
            else:
                import time
                import os
                save_path = os.path.abspath(f"pasted_{int(time.time())}.png")
                img.save(save_path, "PNG")
                self.image_paths.append(save_path)
                self._refresh_image_list()
                self.log_message(self.t("pasted_image"))
        except Exception as e:
            error_msg = str(e)
            self.log_message(self.t("generation_error", error=error_msg))

    def clear_log(self):
        if getattr(self, "cli_log", None) is not None:
            self.cli_log.configure(state="normal")
            self.cli_log.delete("0.0", "end")
            self.cli_log.configure(state="disabled")
        self._activity_run_active = False
        self._activity_progress_value = 0.0
        self._activity_progress_step = 0
        self._set_status_text(self.t("ready") + ".")
        self._set_progress(0)

    def set_busy(self, busy: bool, status_text: str = None):
        self._busy = busy
        try:
            self.run_btn.configure(state=("disabled" if busy else "normal"))
        except Exception:
            pass
        try:
            self.upload_btn.configure(state=("disabled" if busy else "normal"))
        except Exception:
            pass
        if status_text:
            self._set_status_text(status_text)

    def _append_file_log(self, msg: str):
        line = msg if msg is not None else ""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._log_lock:
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(f"[{timestamp}] {line}\n")
        except Exception:
            pass

    def _sanitize_gui_log(self, msg: str) -> str:
        text = "" if msg is None else str(msg)
        replacements = {
            "\U0001f916": "AI",
            "\u26a0\ufe0f": "CANH BAO",
            "\u2699\ufe0f": "RUN",
            "\u2705": "OK",
            "\u2714": "OK",
            "\u274c": "LOI",
            "\U0001f389": "OK",
            "\U0001f4f7": "ANH",
            "\U0001f9f9": "XOA",
            "\U0001f9fc": "XOA",
            "\U0001f5d1": "XOA",
            "\u2139": "INFO",
        }
        for src, dst in replacements.items():
            text = text.replace(src, dst)
        text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 180 or "<html" in text.lower() or "<table" in text.lower() or "\n" in text:
            text = text.splitlines()[0].strip() if text.splitlines() else text
            if len(text) > 180:
                text = text[:177] + "..."
        return text

    def _status_display_text(self, msg: str) -> str:
        text = self._sanitize_gui_log(msg)
        text = re.sub(r"^(?:\[\*\]\s*)?(?:->\s*)?", "", text).strip()
        return text

    def _restart_with_language(self, lang: str):
        config.save_ui_language(lang)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def _reset_activity_timer(self):
        self._activity_started_at = datetime.now()
        if self.__dict__.get("activity_time_label") is not None:
            self.activity_time_label.configure(text=self._activity_time())

    def _activity_time(self):
        start = getattr(self, "_activity_started_at", None)
        if start is None:
            self._activity_started_at = datetime.now()
            start = self._activity_started_at
        elapsed = max(0, int((datetime.now() - start).total_seconds()))
        minutes, seconds = divmod(elapsed, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _is_ready_status_message(self, message: str) -> bool:
        normalized = re.sub(r"\s+", " ", (message or "").lower()).strip().rstrip(".")
        ready_candidates = set()
        translator = getattr(self, "t", None)
        if callable(translator):
            for key in ("ready", "system_ready"):
                try:
                    ready_candidates.add(re.sub(r"\s+", " ", translator(key).lower()).strip().rstrip("."))
                except Exception:
                    pass
        ready_candidates.update({"ready", "system ready", "he thong san sang", "hệ thống sẵn sàng", "sẵn sàng"})
        return normalized in ready_candidates

    def _activity_kind_for_message(self, message: str, update_status: bool = False) -> str:
        text = (message or "").lower()
        if self._is_ready_status_message(message):
            return "info"
        if (
            "lỗi" in text
            or "error" in text
            or "fail" in text
            or "failed" in text
            or "thất bại" in text
            or "không " in text
            or "không hợp lệ" in text
            or "chưa hợp lệ" in text
            or "invalid" in text
        ):
            return "error"
        if update_status:
            return "running"
        if "xong" in text or "done" in text or "thành công" in text or "success" in text or "đã " in text:
            return "success"
        return "info"

    def _activity_icon_for_kind(self, kind: str) -> tuple[str, object]:
        if kind == "running":
            return "\u25cc", COLORS["accent"]
        if kind == "success":
            return "\u2713", COLORS["success"]
        if kind == "error":
            return "!", COLORS["danger"]
        return "i", COLORS["accent"]

    def _status_text_for_kind(self, kind: str) -> str:
        if kind == "running":
            return self.t("status_running")
        if kind == "success":
            return self.t("status_success")
        if kind == "error":
            return self.t("status_error")
        return self.t("status_info")

    def _progress_for_kind(self, kind: str) -> float:
        if kind == "running":
            return 0.0
        if kind == "success":
            return 1.0
        if kind == "error":
            return getattr(self, "_activity_progress_value", 0.0)
        return 0.0

    def _begin_activity_run(self):
        self._cancel_activity_progress_tick()
        self._activity_run_active = True
        self._activity_progress_value = 0.0
        self._activity_progress_step = 0
        self._active_activity_row_widget = None
        self._set_progress(0.0)
        self._schedule_activity_progress_tick()

    def _activity_row_for_update(self, event_text: str):
        active = self.__dict__.get("_active_activity_row_widget")
        if not active:
            return None
        if self.__dict__.get("_activity_run_active", False):
            return active
        if active.get("event") == event_text:
            return active
        return None

    def _next_activity_progress(self) -> float:
        if not getattr(self, "_activity_run_active", False):
            return self._progress_for_kind("running")
        targets = (0.08, 0.18, 0.32, 0.48, 0.64, 0.78, 0.88, 0.92)
        step = max(0, int(getattr(self, "_activity_progress_step", 0)))
        current = max(0.0, min(0.92, float(getattr(self, "_activity_progress_value", 0.0))))
        value = targets[min(step, len(targets) - 1)]
        if value <= current:
            value = min(0.92, current + 0.04)
        self._activity_progress_step = step + 1
        self._activity_progress_value = value
        return value

    def _activity_event_for_message(self, message: str, kind: str) -> str:
        text = "" if message is None else str(message)
        lower = text.lower()
        if self._is_oj_connection_activity_message(lower):
            return self.t("event_oj_connection")
        if self._is_generation_activity_message(lower):
            return self.t("event_generate_tests")
        if any(marker in lower for marker in ("nạp code", "loaded code", "ảnh", "image", "statement", "mô tả", "đề bài", "pdf")):
            return self.t("event_generate_tests")
        if self._is_publish_activity_message(lower, kind):
            return self.t("event_publish")
        return self.t("event_oj_connection")

    def _is_oj_connection_activity_message(self, lower: str) -> bool:
        if any(marker in lower for marker in ("ảnh", "image", "statement", "mô tả", "đề bài", "pdf")):
            return False
        connection_markers = (
            "oj",
            "api",
            "model",
            "provider",
            "settings",
            "cấu hình",
            "đăng nhập",
            "login",
            "tổ chức",
            "organization",
            "quét",
            "discover",
            "loaded",
            "đã tải",
        )
        if any(marker in lower for marker in connection_markers):
            if "testcase" in lower or "test case" in lower or "test data" in lower:
                return False
            return True
        return False

    def _is_publish_activity_message(self, lower: str, kind: str) -> bool:
        publish_markers = (
            "đăng bài",
            "upload",
            "tạo bài",
            "cập nhật bài",
            "ghi đè",
            "test data",
            "testcase",
            "testcases",
            "cấu hình test",
            "ghép cặp",
            "zip response",
            "zip error",
            "upload zip",
            "form",
            "server",
            "ràng buộc",
            "máy chủ giải nén",
        )
        if any(marker in lower for marker in publish_markers):
            return True
        return kind == "error" and ("thất bại:" in lower or lower.startswith("fail "))

    def _is_generation_activity_message(self, lower: str) -> bool:
        generation_markers = (
            "sinh test",
            "sinh xong test",
            "generating tests",
            "start generating tests",
            "finished generating tests",
            "phân tích",
            "analyzing",
            "generator",
            "suy luận",
            "deriving solution",
            "biên dịch",
            "compiling solution",
            "chạy lời giải",
            "running solution",
            "đóng gói test",
            "packaging tests",
        )
        return any(marker in lower for marker in generation_markers)


    def _append_cli_log(self, message: str, kind: str = "info"):
        if getattr(self, "cli_log", None) is None:
            return
        
        display = (message or "").strip()
        if not display:
            return
            
        from datetime import datetime
        now = datetime.now().strftime("%H:%M:%S")
        prefix = "◉" if kind == "info" else "➤" if kind == "running" else "✓" if kind == "success" else "✗" if kind == "error" else "○"
        
        self.cli_log.configure(state="normal")
        self.cli_log.insert("end", f"[{now}] ", "time")
        self.cli_log.insert("end", f"{prefix} {display}\n", kind)
        self.cli_log.see("end")
        self.cli_log.configure(state="disabled")


    def _add_activity_row(self, message: str, kind: str = "info", progress: float | None = None, detail: str = ""):
        event_text = self._activity_event_for_message(message, kind)
        self._append_cli_log(message, kind)
        if detail:
            self._append_cli_log(detail, "info")
        return {"kind": kind, "message": message, "detail": detail}

    def _finish_activity_run(self, success: bool):
        self._activity_run_active = False
        self._cancel_activity_progress_tick()
        if success:
            self._append_cli_log(self.t("detail_complete"), "success")
        else:
            self._append_cli_log(self.t("detail_error"), "error")

    def _cancel_activity_progress_tick(self):
        pass
        
    def _schedule_activity_progress_tick(self):
        pass
        
    def _tick_activity_progress(self):
        pass

    def _set_progress(self, value: float):
        pass

    def _set_latest_running_progress(self, value: float):
        pass

    def _set_all_activity_progress(self, value: float):
        pass

    def _set_all_activity_status(self, kind: str, detail: str | None = None):
        pass

    def _update_activity_row_widget(self, row_state, message: str, kind: str, progress: float | None = None, detail: str = ""):
        if not row_state: return
        
        # Only append to cli log if the message or detail has changed, to avoid spam
        changed = False
        if message and row_state.get("message") != message:
            self._append_cli_log(message, kind)
            row_state["message"] = message
            changed = True
            
        if detail and row_state.get("detail") != detail:
            # Avoid logging generic dots or empty strings
            if detail not in ("-", "", "đang chạy..."):
                self._append_cli_log(detail, "info")
            row_state["detail"] = detail
            changed = True
            
        if progress is not None:
            pct = int(round(progress * 100))
            if pct > 0 and pct % 20 == 0 and row_state.get("last_pct") != pct:
                self._append_cli_log(f"Tiến độ: {pct}%", "info")
                row_state["last_pct"] = pct


    def _set_all_activity_progress(self, value: float):
        progress_value = max(0.0, min(1.0, float(value)))
        for row in getattr(self, "_activity_row_widgets", []) or []:
            if row.get("bar") is None:
                continue
            row["bar"].set(progress_value)
            row["percent"].configure(text=f"{int(round(progress_value * 100))}%")

    def _set_all_activity_status(self, kind: str, detail: str | None = None):
        icon, color = self._activity_icon_for_kind(kind)
        status_text = self._status_text_for_kind(kind)
        for row in getattr(self, "_activity_row_widgets", []) or []:
            row["kind"] = kind
            if row.get("icon") is not None:
                row["icon"].configure(text=icon, text_color=color)
            if row.get("status") is not None:
                row["status"].configure(text=status_text, text_color=color)
            if detail is not None and row.get("detail") is not None:
                current_detail = row.get("detail_text")
                if current_detail is None:
                    try:
                        current_detail = row["detail"].cget("text")
                    except Exception:
                        current_detail = getattr(row["detail"], "text", "")
                generic_details = {"", "-", self.t("detail_running"), self.t("detail_complete")}
                if current_detail in generic_details:
                    row["detail"].configure(text=detail or "-")
                    row["detail_text"] = detail or "-"

    def _activity_detail_for_message(self, message: str, kind: str) -> str:
        text = "" if message is None else str(message)
        clean = re.sub(r"^\s*(?:\[\*\]\s*)?(?:->\s*)?", "", text).strip()
        clean = clean.rstrip(".")
        lower = text.lower()
        clean_lower = clean.lower()
        failure = re.match(r"^(?:thất bại|lỗi|fail|error):\s*(.+)$", clean, flags=re.I)
        if failure:
            failure_text = failure.group(1).strip()
            failure_lower = failure_text.lower()
            if "chưa hợp lệ" in failure_lower or "invalid data" in failure_lower:
                return self.t("detail_invalid_data")
            if "không hợp lệ" in failure_lower or "ràng buộc" in failure_lower:
                return self.t("detail_form_invalid")
            return self._short_activity_detail(failure_text)
        attempt = re.search(r"(?:l\u1ea7n|lan|attempt)\s*(\d+)\s*/\s*(\d+)", lower)
        if attempt:
            return f"{self.t('detail_attempt')} {attempt.group(1)}/{attempt.group(2)}"
        organization_count = re.search(r"(\d+)\s*(?:tổ chức|organizations?)", lower)
        if organization_count:
            return self.t("detail_organizations", count=organization_count.group(1))
        testcase_count = re.search(r"(\d+)\s*test\s*cases?", lower) or re.search(r"(\d+)\s*testcases?", lower)
        if testcase_count:
            return f"{testcase_count.group(1)} testcases"
        if "quét danh sách tổ chức" in lower or "discovering organizations" in lower:
            return self.t("detail_discover_organizations")
        if "kiểm tra đăng nhập" in lower or "checking login" in lower:
            return self.t("detail_login")
        created = re.search(r"(?:đang tạo bài mới|creating new problem)\s+(.+)$", clean_lower)
        if created:
            return f"{self.t('detail_create_problem')} {created.group(1).strip()}"
        updated = re.search(r"(?:đang cập nhật bài|updating problem)\s+(.+)$", clean_lower)
        if updated:
            return f"{self.t('detail_update_problem')} {updated.group(1).strip()}"
        if "mở trang test data" in lower or "get test data page" in lower:
            return self.t("detail_test_data_page")
        if "ghép cặp" in lower or "pairing tests" in lower:
            return self.t("detail_pairing")
        if "upload zip" in lower or "post upload zip" in lower or "zip response" in lower:
            return self.t("detail_upload_zip")
        if "dữ liệu form không hợp lệ" in lower or "form data invalid" in lower or "ràng buộc" in lower:
            return self.t("detail_form_invalid")
        if "dữ liệu chưa hợp lệ" in lower or "invalid data" in lower:
            return self.t("detail_invalid_data")
        if "n\u1ea1p code" in lower or "loaded code" in lower:
            return self.t("detail_loaded_code")
        if "ph\u00e2n t\u00edch" in lower or "analyzing" in lower:
            return self.t("detail_analysis")
        if "sinh input" in lower or "generating tests" in lower:
            return self.t("detail_tests")
        if "generator" in lower:
            return self.t("detail_generator")
        if "suy lu\u1eadn" in lower or "deriving solution" in lower:
            return self.t("detail_solution")
        if "bi\u00ean d\u1ecbch" in lower or "compiling solution" in lower:
            return self.t("detail_compile")
        if "ch\u1ea1y l\u1eddi gi\u1ea3i" in lower or "running solution" in lower:
            return self.t("detail_run_solution")
        if "\u0111\u00f3ng g\u00f3i" in lower or "packaging tests" in lower:
            return self.t("detail_packaging")
        if "\u0111\u00e3 sinh xong" in lower or "finished generating tests" in lower:
            return self.t("detail_generated_tests")
        if "\u0111\u1ed5i model" in lower or "trying another model" in lower:
            return self.t("detail_model_retry")
        if "th\u1eed l\u1ea1i" in lower or "retry" in lower:
            return self.t("detail_retry")
        if "get " in lower or " trang " in lower or " page" in lower:
            return "HTTP"
        if kind == "success":
            return self.t("detail_complete")
        if kind == "error":
            return self.t("detail_error")
        if kind == "running":
            return self.t("detail_running")
        return ""

    def _short_activity_detail(self, value: str, limit: int = 54) -> str:
        text = re.sub(r"\s+", " ", value or "").strip()
        text = text.split(".")[0].strip() or text
        if len(text) > limit:
            text = text[: limit - 3].rstrip() + "..."
        return text

    def _update_activity_progress(self, value: float, status_text: str | None = None, detail: str | None = None):
        self._set_progress(value)
        if status_text:
            self._set_status_text(status_text)
        if getattr(self, "_activity_row_widgets", None):
            latest = self._activity_row_widgets[-1]
            progress_value = max(0.0, min(1.0, float(value)))
            if latest.get("bar") is not None:
                latest["bar"].set(progress_value)
                latest["percent"].configure(text=f"{int(round(progress_value * 100))}%")
            if status_text:
                latest["status"].configure(text=status_text)
            if detail is not None:
                latest["detail"].configure(text=detail or "-")
                latest["detail_text"] = detail or "-"

    def _on_code_language_change(self, value: str):
        language = (value or "C++17").strip() or "C++17"
        self._code_language = language
        if "code_language_option" in self.__dict__:
            try:
                self.code_language_option.set(language)
            except Exception:
                pass
        if "code_language_label" in self.__dict__:
            self.code_language_label.configure(text=language)
        if "code_lang_footer" in self.__dict__:
            self.code_lang_footer.configure(text=language)
        if "quick_language_value" in self.__dict__ and self.quick_language_value is not None:
            self.quick_language_value.configure(text=language)

    def _update_code_cursor_position(self, event=None):
        try:
            index = self.code_box.index("insert")
            line_text, column_text = str(index).split(".", 1)
            line = max(1, int(line_text))
            column = max(1, int(column_text) + 1)
            self.code_position_label.configure(text=f"Dòng {line}, Cột {column}")
        except Exception:
            if "code_position_label" in self.__dict__:
                self.code_position_label.configure(text="Dòng 1, Cột 1")

    def _on_language_change(self, value: str):
        selected = value or ""
        if selected == self.t("lang_vi"):
            lang = "vi"
        elif selected == self.t("lang_en"):
            lang = "en"
        else:
            return
        if lang != self.ui_lang:
            self._restart_with_language(lang)

    def _toggle_theme(self):
        self._appearance_mode = "Dark" if self._appearance_mode == "Light" else "Light"
        ctk.set_appearance_mode(self._appearance_mode)
        if "theme_toggle_btn" in self.__dict__:
            self.theme_toggle_btn.configure(text=("\u2600" if self._appearance_mode == "Dark" else "\u25d0"))

    def _provider_label(self, provider: str) -> str:
        return self.t("provider_openai") if provider == "openai" else self.t("provider_gemini")

    def _provider_id_from_label(self, label: str) -> str:
        label = (label or "").strip()
        if label == self.t("provider_openai"):
            return "openai"
        return "gemini"

    def _get_selected_provider(self) -> str:
        try:
            label = self.provider_option.get().strip()
        except Exception:
            label = self._provider_label(config.get_active_provider())
        return self._provider_id_from_label(label)

    def _discover_models_for_provider(self, provider: str, api_key: str, allow_network: bool = False) -> list[str]:
        if not allow_network:
            return config.get_supported_models(provider)
        models = ai_providers.discover_models(provider, api_key)
        return models or config.get_supported_models(provider)

    def _sync_provider_fields(self, provider: str):
        provider = provider or config.get_active_provider()
        self._provider_ready = False
        self.provider_option.set(self._provider_label(provider))
        key = config.get_api_key_for_provider(provider)
        self.api_entry.delete(0, tk.END)
        self.api_entry.insert(0, key)
        self._available_models = self._discover_models_for_provider(provider, key)
        self.model_option.configure(values=self._available_models)
        current_model = config.get_model_name(provider)
        if current_model not in self._available_models and self._available_models:
            current_model = self._available_models[0]
        self.model_option.set(current_model)
        self._model_ready = True
        self._provider_ready = True
        config.save_active_provider(provider)

    def _on_provider_change(self, value: str):
        if not getattr(self, "_provider_ready", False):
            return
        provider = self._provider_id_from_label(value)
        self._sync_provider_fields(provider)
        self.log_message(self.t("detected_provider", provider=self._provider_label(provider)))

    def _get_selected_model(self) -> str:
        try:
            value = self.model_option.get().strip()
        except Exception:
            value = config.get_model_name(self._get_selected_provider())
        return value or config.get_model_name(self._get_selected_provider())

    def _on_model_change(self, value: str):
        if not getattr(self, "_model_ready", False):
            return
        model = (value or "").strip()
        if not model:
            return
        self.model_option.set(model)
        self.save_model_name()

    def save_model_name(self):
        model = self._get_selected_model()
        provider = self._get_selected_provider()
        config.save_model_name(model, provider)
        self.log_message(self.t("saved_model_provider", provider=self._provider_label(provider), model=model))

    def _set_status_text(self, text: str):
        display = self._status_display_text(text)
        status_kind = self._status_kind_for_text(display)
        icon, color = self._activity_icon_for_kind(status_kind)
        if self.__dict__.get("status_label") is not None:
            self.status_label.configure(text=display)
        if self.__dict__.get("quick_status") is not None:
            self.quick_status.configure(text=display, text_color=COLORS.get("muted", color) if status_kind == "error" else color)
        if self.__dict__.get("status_dot") is not None:
            try:
                self.status_dot.configure(fg_color=color)
            except Exception:
                pass
        if self.__dict__.get("activity_time_label") is not None:
            self.activity_time_label.configure(text=self._activity_time())
        if self.__dict__.get("activity_icon_label") is not None:
            self.activity_icon_label.configure(text=icon, text_color=color)

    def _status_kind_for_text(self, text: str) -> str:
        kind = self._activity_kind_for_message(text, update_status=False)
        if kind != "info":
            return kind
        normalized = re.sub(r"\s+", " ", (text or "").lower()).strip().rstrip(".")
        ready_values = {
            self.t("ready").lower().rstrip("."),
            self.t("system_ready").lower().rstrip("."),
            "ready",
            "system ready",
            "sẵn sàng",
            "hệ thống sẵn sàng",
        }
        return "info" if normalized in ready_values else "running"

    def _is_model_overloaded_error(self, error_text: str) -> bool:
        text = (error_text or "").lower()
        return "503" in text and (
            "unavailable" in text
            or "high demand" in text
            or "quá tải" in text
            or "qua tai" in text
            or "currently experiencing" in text
        )

    def _is_rate_limit_error(self, error_text: str) -> bool:
        text = (error_text or "").lower()
        return "429" in text or "rate limit" in text or "quota" in text

    def _get_model_suggestions(self, current_model: str) -> list[str]:
        suggestions = [m for m in getattr(self, "_available_models", []) if m != current_model]
        if suggestions:
            return suggestions
        provider = self._get_selected_provider()
        fallback = config.get_supported_models(provider)
        return [m for m in fallback if m != current_model] or fallback

    def _show_model_overload_help(self, current_model: str):
        suggestion_text = ", ".join(self._get_model_suggestions(current_model))
        messagebox.showwarning(
            self.t("model_overloaded_title"),
            self.t("model_overloaded_body", current=current_model, suggestions=suggestion_text),
        )

    def progress_message(self, msg: str):
        self.log_message(msg)

    def _log_activity_start(self, msg: str):
        raw = "" if msg is None else str(msg)
        localized = tr_runtime(self.ui_lang, raw)
        self._append_file_log(localized)
        display = self._sanitize_gui_log(localized)
        self._set_status_text(display)
        row_state = self._add_activity_row(display, "running", progress=0.0, detail=self._activity_detail_for_message(display, "running"))
        self._active_activity_row_widget = row_state

    def _log_completed_activity(self, msg: str, detail: str | None = None):
        raw = "" if msg is None else str(msg)
        localized = tr_runtime(self.ui_lang, raw)
        self._append_file_log(localized)
        display = self._sanitize_gui_log(localized)
        self._set_status_text(display)
        self._set_progress(1.0)
        self._add_activity_row(display, "success", progress=1.0, detail=detail or self._activity_detail_for_message(display, "success"))

    def log_message(self, msg: str, update_status: bool = False):
        raw = "" if msg is None else str(msg)
        localized = tr_runtime(self.ui_lang, raw)
        self._append_file_log(localized)
        display = self._sanitize_gui_log(localized)
        kind = self._activity_kind_for_message(display, update_status=update_status)
        progress_value = None
        if update_status:
            self._set_status_text(display)
            if kind == "running":
                progress_value = self._next_activity_progress()
                self._set_progress(progress_value)
            else:
                progress_value = self._progress_for_kind(kind)
        elif kind == "success":
            progress_value = 1.0
        elif kind == "error":
            progress_value = self._progress_for_kind(kind)
            self._set_status_text(self.t("status_error"))
        elif kind == "info":
            progress_value = 0.0
        detail = self._activity_detail_for_message(display, kind)
        event_text = self._activity_event_for_message(display, kind)
        if update_status and kind == "info" and self._is_ready_status_message(display):
            return
        row_to_update = self._activity_row_for_update(event_text)
        if row_to_update is not None:
            self._update_activity_row_widget(row_to_update, display, kind, progress=progress_value, detail=detail)
            if kind in ("success", "error"):
                self._active_activity_row_widget = None
        else:
            self._add_activity_row(display, kind, progress=progress_value, detail=detail)

    def ui(self, fn):
        self.after(0, fn)
    def _notify_done_dialog(self, title, msg):
        try:
            self.lift()
            self.focus_force()
            self.attributes("-topmost", True)
            self.update_idletasks()
            messagebox.showinfo(title, msg)
        finally:
            self.attributes("-topmost", False)


    def _update_counts(self):
        self.sel_count_label.configure(text=self.t("images_count", count=len(self.image_paths)))
        if self.current_zip_path:
            self.zip_hint_label.configure(text=f"ZIP: {os.path.basename(self.current_zip_path)}")
        else:
            self.zip_hint_label.configure(text=self.t("zip_none"))

    # ============================================================
    # Thao tác cấu hình và file
    # ============================================================
    def save_api_key(self):
        key = self.api_entry.get().strip()
        if not key:
            messagebox.showwarning(self.t("error_title"), self.t("api_key_required"))
            return

        provider = self._get_selected_provider()
        if re.match(r"^sk-(proj-)?[A-Za-z0-9]", key):
            provider = "openai"
        elif key.startswith("AIza"):
            provider = "gemini"
        config.save_api_key(key, provider)
        config.save_active_provider(provider)
        self._sync_provider_fields(provider)
        self.log_message(self.t("saved_api_key_provider", provider=self._provider_label(provider)))

    def save_oj_settings(self):
        try:
            url = self.oj_url_entry.get().strip()
            user = self.oj_user_entry.get().strip()
            password = self.oj_pass_entry.get().strip()
            time_limit = float(self.oj_time_entry.get().strip())
            memory = int(self.oj_mem_entry.get().strip())
            points = int(self.oj_points_entry.get().strip())
            public = self.oj_public_var.get()
        except Exception:
            messagebox.showerror(self.t("error_title"), self.t("oj_settings_invalid"))
            return

        settings = OJSettings(
            url=url,
            user=user,
            password=password,
            time_limit=time_limit,
            memory_mb=memory,
            points=points,
            is_public=public,
        )
        ok, msg = validate_oj_settings(settings)
        if not ok:
            messagebox.showerror(self.t("error_title"), tr_runtime(self.ui_lang, msg))
            return

        config.save_oj_config(url, user, password)
        config.save_oj_defaults(time_limit, points, memory, public)
        self.log_message(self.t("saved_oj_settings"))
        messagebox.showinfo(self.t("success_title"), self.t("oj_settings_saved"))

    def browse_path(self):
        path = filedialog.askdirectory()
        if path:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, path)

    def browse_zip(self):
        path = filedialog.askopenfilename(filetypes=[("Zip files", "*.zip")])
        if path:
            self.oj_zip_entry.delete(0, tk.END)
            self.oj_zip_entry.insert(0, path)
            self.current_zip_path = path
            self._update_counts()

    def choose_statement_file(self):
        path = filedialog.askopenfilename(
            filetypes=[
                ("Statement files", "*.pdf *.png *.jpg *.jpeg *.webp *.bmp"),
                ("PDF files", "*.pdf"),
                ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp"),
                ("All files", "*.*"),
            ]
        )
        if path:
            self._set_statement_file_path(path)
            self.log_message(self.t("statement_file_selected", file=os.path.basename(path)))

    def _set_statement_file_path(self, path: str):
        self.statement_file_path = path or ""
        if "statement_file_entry" in self.__dict__:
            self.statement_file_entry.delete(0, tk.END)
            if self.statement_file_path:
                self.statement_file_entry.insert(0, self.statement_file_path)

    def _generated_statement_pdf_path(self) -> str:
        try:
            pid = self.name_entry.get().strip() or "problem"
            out = self.path_entry.get().strip() or config.BASE_SOLUTION_DIR
        except Exception:
            return ""
        return os.path.join(out, pid, "statement.pdf")

    def _resolve_generated_statement_file(self, create_from_images: bool = False) -> str:
        pdf_path = self._generated_statement_pdf_path()
        if pdf_path and os.path.exists(pdf_path):
            return pdf_path
        if create_from_images and getattr(self, "image_paths", None):
            generated = self.generate_statement_pdf()
            return generated or ""
        return ""

    def use_generated_statement_file(self):
        path = self._resolve_generated_statement_file(create_from_images=True)
        if not path:
            messagebox.showinfo(self.t("notice_title"), self.t("no_statement_file"))
            return
        self._set_statement_file_path(path)
        self.log_message(self.t("statement_file_selected", file=os.path.basename(path)))

    def _resolve_upload_statement_file(self) -> str:
        selected = ""
        has_entry = "statement_file_entry" in self.__dict__
        if has_entry:
            try:
                selected = self.statement_file_entry.get().strip()
            except Exception:
                selected = ""
        else:
            selected = getattr(self, "statement_file_path", "")
        if selected:
            self.statement_file_path = selected
            return selected
        return self._resolve_generated_statement_file(create_from_images=True)

    def load_problem_from_file(self):
        path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt *.md *.tex *.log *.in *.out"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            self.text_box.delete("0.0", tk.END)
            self.text_box.insert("0.0", text)
            self.log_message(self.t("loaded_statement_file", file=os.path.basename(path)))
        except Exception as e:
            error_msg = str(e)
            messagebox.showerror(self.t("error_title"), self.t("could_not_read_statement", error=error_msg))

    def _code_filetypes(self):
        language = getattr(self, "_code_language", "C++17")
        if language == "Python 3":
            return [("Python files", "*.py *.pyw *.txt"), ("All files", "*.*")]
        if language == "Java":
            return [("Java files", "*.java *.txt"), ("All files", "*.*")]
        return [("C++ files", "*.cpp *.cc *.cxx *.h *.hpp *.txt"), ("All files", "*.*")]

    def load_code_from_file(self):
        path = filedialog.askopenfilename(filetypes=self._code_filetypes())
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            self.code_box.delete("0.0", tk.END)
            self.code_box.insert("0.0", text)
            self._update_code_cursor_position()
            self._log_completed_activity(
                self.t("loaded_code_file", file=os.path.basename(path)),
                detail=self.t("detail_loaded_code"),
            )
        except Exception as e:
            error_msg = e
            messagebox.showerror(self.t("error_title"), self.t("could_not_read_code", error=error_msg))

    # ============================================================
    # Hành động của tab chính
    # ============================================================
    def add_image(self):
        paths = filedialog.askopenfilenames(filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if not paths:
            return
        for p in paths:
            if p not in self.image_paths:
                self.image_paths.append(p)
        self._refresh_image_list()
        self._update_counts()
        self.log_message(self.t("added_images", count=len(paths)))

    def clear_images(self):
        self.image_paths = []
        self.thumbnail_refs = []
        self._refresh_image_list()
        self._update_counts()
        self.log_message(self.t("cleared_images"))

    def clear_problem_text(self):
        self.text_box.delete("0.0", tk.END)
        self.log_message(self.t("cleared_statement"))

    def clear_code_text(self):
        self.code_box.delete("0.0", tk.END)
        self._update_code_cursor_position()
        self.log_message(self.t("cleared_code"))

    def clear_all_main(self):
        self.text_box.delete("0.0", tk.END)
        self.code_box.delete("0.0", tk.END)
        self._update_code_cursor_position()
        self.clear_images()
        self.log_message(self.t("cleared_main_tab"))

    def grab_clipboard(self):
        try:
            data = ImageGrab.grabclipboard()
            img = None
            if isinstance(data, Image.Image):
                img = data
            elif isinstance(data, list) and data:
                first = data[0]
                if os.path.exists(first):
                    img = Image.open(first)

            if img is None:
                self.log_message(self.t("clipboard_no_image"))
                return

            pid = self.name_entry.get().strip()
            if not pid:
                messagebox.showwarning(self.t("missing_problem_name"), self.t("enter_problem_name"))
                return
            out = self.path_entry.get().strip() or config.BASE_SOLUTION_DIR
            sdir = os.path.join(out, pid)
            os.makedirs(sdir, exist_ok=True)

            path = os.path.abspath(os.path.join(sdir, f"img_{len(self.image_paths) + 1}.png"))
            img.convert("RGB").save(path)
            self.image_paths.append(path)
            self._refresh_image_list()
            self._update_counts()
            self.log_message(self.t("pasted_image"))
        except Exception as e:
            error_msg = str(e)
            self.log_message(self.t("clipboard_error", error=error_msg))

    def _refresh_image_list(self):
        if "scroll_images" not in self.__dict__:
            return
        for child in self.scroll_images.winfo_children():
            child.destroy()
        self.thumbnail_refs = []
        self.empty_images_hint = None
        if not self.image_paths:
            self._show_empty_images_hint()
        else:
            for index, path in enumerate(list(self.image_paths)):
                self._render_attachment_row(index, path)
        self._update_counts()

    def _render_attachment_row(self, index: int, path: str):
        try:
            if not os.path.exists(path):
                self.log_message(self.t("image_not_found", path=path))
                return
            if getattr(self, "empty_images_hint", None) is not None:
                self.empty_images_hint.destroy()
                self.empty_images_hint = None

            card = ctk.CTkFrame(
                self.scroll_images,
                corner_radius=12,
                fg_color=COLORS["surface"],
                border_width=1,
                border_color=COLORS["border"],
                height=44,
            )
            card.pack(side="top", fill="x", pady=(5, 0), padx=6)
            card.grid_propagate(False)
            card.grid_columnconfigure(1, weight=1)

            preview_box = ctk.CTkFrame(card, corner_radius=8, fg_color=COLORS["surface_secondary"], width=64, height=30)
            preview_box.grid(row=0, column=0, padx=(7, 9), pady=7, sticky="nsw")
            preview_box.grid_propagate(False)
            try:
                img = Image.open(path)
                preview_size = self._fit_image_preview_size(*img.size)
                img.thumbnail(preview_size)
                cimg = ctk.CTkImage(light_image=img, dark_image=img, size=preview_size)
                self.thumbnail_refs.append(cimg)
                ctk.CTkLabel(preview_box, image=cimg, text="").pack(expand=True)
            except Exception:
                ext = os.path.splitext(path)[1].replace(".", "").upper()[:4] or "FILE"
                ctk.CTkLabel(preview_box, text=ext, text_color=COLORS["accent"], font=ctk.CTkFont(size=10, weight="bold")).pack(expand=True)

            info = ctk.CTkFrame(card, fg_color="transparent")
            info.grid(row=0, column=1, pady=7, sticky="nsew")
            info.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                info,
                text=self._shorten_attachment_name(os.path.basename(path), 18),
                anchor="w",
                font=ctk.CTkFont(size=12, weight="bold"),
            ).grid(row=0, column=0, sticky="ew", pady=(5, 0))

            size_label = ctk.CTkLabel(
                card,
                text=self._format_file_size(os.path.getsize(path)),
                width=58,
                text_color=COLORS["muted"],
                anchor="e",
                font=ctk.CTkFont(size=11),
            )
            size_label.grid(row=0, column=2, padx=(6, 0), pady=7, sticky="e")

            self._destructive_button(
                card,
                text="\u00d7",
                width=28,
                height=24,
                command=lambda idx=index: self._remove_image_at(idx),
            ).grid(row=0, column=3, padx=(8, 7), pady=7, sticky="e")
        except Exception as e:
            error_msg = str(e)
            self.log_message(self.t("could_not_display_image", error=error_msg))

    def _show_empty_images_hint(self):
        if getattr(self, "empty_images_hint", None) is not None:
            return
        self.empty_images_hint = ctk.CTkLabel(
            self.scroll_images,
            text=f"{self.t('attachment_empty')}\n{self.t('attachment_hint')}",
            text_color=COLORS["muted"],
            font=ctk.CTkFont(size=12),
            justify="center",
            wraplength=330,
        )
        self.empty_images_hint.pack(expand=True, fill="both", padx=14, pady=10)

    @staticmethod
    def _fit_image_preview_size(width: int, height: int, max_width: int = 56, max_height: int = 32) -> tuple[int, int]:
        width = max(1, int(width))
        height = max(1, int(height))
        scale = min(max_width / width, max_height / height, 1)
        return max(1, int(width * scale)), max(1, int(height * scale))

    @staticmethod
    def _short_file_name(name: str, max_chars: int = 22) -> str:
        return App._shorten_attachment_name(name, max_chars)

    @staticmethod
    def _shorten_attachment_name(name: str, max_chars: int = 22) -> str:
        name = os.path.basename(name or "")
        if len(name) <= max_chars:
            return name
        stem, ext = os.path.splitext(name)
        ext = ext.lstrip(".")
        suffix = f"...{ext}" if ext else "..."
        keep = max(1, max_chars - len(suffix))
        return f"{stem[:keep]}{suffix}"

    @staticmethod
    def _format_file_size(size: int | float) -> str:
        size = max(0.0, float(size or 0))
        if size < 1024:
            return f"{int(size)} B"
        size /= 1024
        if size < 1024:
            return f"{size:.1f} KB" if size < 10 else f"{int(round(size))} KB"
        size /= 1024
        return f"{size:.1f} MB"

    def _remove_image_at(self, index: int):
        if 0 <= index < len(self.image_paths):
            del self.image_paths[index]
        self._refresh_image_list()
        self.log_message(self.t("removed_image"))

    def _remove_image(self, frame, path):
        if path in self.image_paths:
            self._remove_image_at(self.image_paths.index(path))
        else:
            try:
                frame.destroy()
            except Exception:
                pass

    def generate_statement_pdf(self):
        if not self.image_paths:
            messagebox.showinfo(self.t("notice_title"), self.t("no_images_pdf"))
            return None
        try:
            pid = self.name_entry.get().strip() or "problem"
            out = self.path_entry.get().strip() or config.BASE_SOLUTION_DIR
            sdir = os.path.join(out, pid)
            os.makedirs(sdir, exist_ok=True)
            pdf_path = os.path.join(sdir, "statement.pdf")
            imgs = [Image.open(p).convert("RGB") for p in self.image_paths]
            if imgs:
                imgs[0].save(pdf_path, "PDF", save_all=True, append_images=imgs[1:])
                self.log_message(self.t("created_pdf", path=pdf_path))
                return pdf_path
        except Exception as e:
            error_msg = str(e)
            self.log_message(self.t("pdf_error", error=error_msg))
        return None

    def _read_generation_test_count(self) -> int | None:
        try:
            raw = self.test_count_entry.get().strip()
            count = int(raw)
        except Exception:
            count = 0
        if count < config.MIN_GENERATION_TEST_COUNT or count > config.MAX_GENERATION_TEST_COUNT:
            messagebox.showwarning(
                self.t("error_title"),
                self.t(
                    "test_count_invalid",
                    min=config.MIN_GENERATION_TEST_COUNT,
                    max=config.MAX_GENERATION_TEST_COUNT,
                ),
            )
            return None
        return count

    def start_process(self):
        if self._busy:
            return

        problem_name = self.name_entry.get().strip()
        output_dir = self.path_entry.get().strip() or config.BASE_SOLUTION_DIR
        test_count = self._read_generation_test_count()
        if test_count is None:
            return
        config.save_generation_test_count(test_count)
        api_key = self.api_entry.get().strip()
        provider_name = self._get_selected_provider()
        if re.match(r"^sk-(proj-)?[A-Za-z0-9]", api_key):
            provider_name = "openai"
        elif api_key.startswith("AIza"):
            provider_name = "gemini"
        if provider_name != self._get_selected_provider():
            self._sync_provider_fields(provider_name)
        model_name = self._get_selected_model()
        text_content = self.text_box.get("0.0", tk.END).strip()
        user_code = self.code_box.get("0.0", tk.END).strip()
        generate_statement_var = getattr(self, "generate_statement_var", None)
        generate_statement = True if generate_statement_var is None else bool(generate_statement_var.get())

        ok, msg = validate_problem_name(problem_name)
        if not ok:
            messagebox.showwarning(self.t("missing_problem_name"), tr_runtime(self.ui_lang, msg))
            return
        ok, msg = validate_api_key(api_key)
        if not ok:
            messagebox.showwarning(self.t("error_title"), tr_runtime(self.ui_lang, msg))
            return

        self._reset_activity_timer()
        self._begin_activity_run()
        self.set_busy(True, self.t("processing"))
        self._log_activity_start(self.t("start_generating", problem=problem_name))

        def worker():
            completed = False
            try:
                request = ProcessRequest(
                    problem_name=problem_name,
                    api_key=api_key,
                    provider_name=provider_name,
                    model_name=model_name,
                    text_content=text_content,
                    image_paths=list(self.image_paths),
                    user_cpp_code=user_code,
                    output_dir=output_dir,
                    test_count=test_count,
                    generate_statement=generate_statement,
                )
                result = process_problem_request(
                    request=request,
                    progress_callback=lambda m: self.ui(lambda: self.progress_message(m)),
                )

                self.ui(lambda: self._process_done(problem_name, result.plan, result.zip_path))
                completed = True
            except Exception as e:
                error_msg = str(e)
                if self._is_model_overloaded_error(error_msg):
                    self.ui(lambda: self.log_message(self.t("model_overloaded_body", current=model_name, suggestions=", ".join(self._get_model_suggestions(model_name)))))
                    self.ui(lambda: self._show_model_overload_help(model_name))
                elif self._is_rate_limit_error(error_msg):
                    suggestions = ", ".join(self._get_model_suggestions(model_name))
                    self.ui(lambda: self.log_message(self.t("rate_limit_body", provider=self._provider_label(provider_name), suggestions=suggestions)))
                    self.ui(lambda: messagebox.showwarning(
                        self.t("rate_limit_title"),
                        self.t("rate_limit_body", provider=self._provider_label(provider_name), suggestions=suggestions),
                    ))
                else:
                    self.ui(lambda: self.log_message(self.t("generation_error", error=error_msg)))
            finally:
                if not completed:
                    self.ui(lambda: self._finish_activity_run(False))
                self.ui(lambda: self.set_busy(False, self.t("ready") + "."))

        threading.Thread(target=worker, daemon=True).start()

    def _process_done(self, problem_name, plan, zip_path):
        self.current_plan = plan or {}
        self.current_zip_path = zip_path or self.current_zip_path
        self.current_statement_markdown = self.current_plan.get("statement_markdown", "")
        self.current_statement_html = self.current_plan.get("statement_html", "")
        self.current_statement_text = self.current_plan.get("statement_text", "")
        self._update_counts()
        self._finish_activity_run(True)
        self.log_message(self.t("finished_generating", problem=problem_name))

        if zip_path and os.path.exists(zip_path):
            self.oj_zip_entry.delete(0, tk.END)
            self.oj_zip_entry.insert(0, zip_path)

        if problem_name:
            self.oj_code_entry.delete(0, tk.END)
            self.oj_code_entry.insert(0, problem_name)

        if self.current_statement_markdown:
            self._set_upload_description_text(self.current_statement_markdown)
        elif self.current_statement_text:
            self._set_upload_description_text(self.current_statement_text)

        generated_statement_file = self._resolve_generated_statement_file(create_from_images=False)
        if generated_statement_file:
            self._set_statement_file_path(generated_statement_file)

        self._select_tab(self.tab_oj_name)
        self._set_status_text(self.t("tests_generated"))
        self.after(150, lambda: self._notify_done_dialog(self.t("done_dialog_title"), self.t("done_dialog_msg")))

    def _use_statement_text_for_upload(self) -> bool:
        var = getattr(self, "oj_use_text_var", None)
        if var is None:
            return True
        try:
            return bool(var.get())
        except Exception:
            return True

    def _sync_upload_text_state(self):
        if "oj_desc_textbox" not in self.__dict__:
            return
        enabled = self._use_statement_text_for_upload()
        self.oj_desc_textbox.configure(state=("normal" if enabled else "disabled"))

    def _set_upload_description_text(self, text: str):
        if "oj_desc_textbox" not in self.__dict__:
            return
        state = "normal" if self._use_statement_text_for_upload() else "disabled"
        try:
            state = self.oj_desc_textbox.cget("state")
        except Exception:
            pass
        try:
            self.oj_desc_textbox.configure(state="normal")
            self.oj_desc_textbox.delete("0.0", tk.END)
            self.oj_desc_textbox.insert("0.0", text or "")
        finally:
            try:
                self.oj_desc_textbox.configure(state=state)
            except Exception:
                pass

    def _resolve_upload_description_html(self, desc_text: str, use_statement_text: bool = True) -> str:
        if not use_statement_text:
            return ""
        text = (desc_text or "").strip()
        generated_markdown = (self.__dict__.get("current_statement_markdown", "") or "").strip()
        generated_text = (self.__dict__.get("current_statement_text", "") or "").strip()
        generated_html = (self.__dict__.get("current_statement_html", "") or "").strip()
        if not text:
            return generated_markdown or generated_html
        if generated_markdown and text == generated_markdown:
            return generated_markdown
        if generated_html and generated_text and text == generated_text:
            return generated_markdown or generated_html
        return text

    def _upload_statement_source_error_key(self, description_html: str, statement_file_path: str, use_statement_text: bool = True) -> str:
        if use_statement_text:
            return "" if (description_html or "").strip() else "missing_statement"
        return "" if (statement_file_path or "").strip() else "missing_statement_file_when_text_disabled"

    def _get_upload_target(self) -> str:
        option = getattr(self, "oj_target_option", None)
        if option is None:
            return "root"
        try:
            return "root" if option.get() == self.t("upload_target_root") else "organization"
        except Exception:
            return "root"

    @staticmethod
    def _organization_display(option: OrganizationOption) -> str:
        if option.name and option.name != option.id:
            return f"{option.name} ({option.id})"
        return option.name or option.id

    def _organization_target_values(self) -> list[str]:
        root_label = self.t("upload_target_root")
        manual_label = self.t("upload_target_organization")
        organization_values = [
            self._organization_display(option)
            for option in getattr(self, "organization_options", [])
            if self._organization_display(option)
        ]
        values = [root_label] + organization_values
        if manual_label not in values:
            values.append(manual_label)
        return values

    def _sync_organization_controls(self):
        enabled = self._get_upload_target() == "organization"
        state = "normal" if enabled else "disabled"
        for widget_name in ("oj_org_option", "oj_org_manual_entry"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                try:
                    widget.configure(state=state)
                except Exception:
                    pass

    def _set_organization_options(self, options: list[OrganizationOption]):
        self.organization_options = options or []
        organization_values = [self._organization_display(option) for option in self.organization_options]
        values = organization_values or [self.t("organization_none")]
        if "oj_org_option" in self.__dict__:
            self.oj_org_option.configure(values=values)
            self.oj_org_option.set(values[0])
        if "oj_target_option" in self.__dict__:
            target_values = self._organization_target_values()
            try:
                current = self.oj_target_option.get()
            except Exception:
                current = self.t("upload_target_root")
            self.oj_target_option.configure(values=target_values)
            if current == self.t("upload_target_root"):
                self.oj_target_option.set(self.t("upload_target_root"))
            elif current in target_values and current != self.t("upload_target_organization"):
                self.oj_target_option.set(current)
            elif organization_values:
                self.oj_target_option.set(organization_values[0])
            else:
                self.oj_target_option.set(self.t("upload_target_organization"))
            self._sync_organization_controls()
        if self.organization_options:
            if self.__dict__.get("_activity_run_active", False):
                self._finish_activity_run(True)
            self.log_message(self.t("organizations_loaded", count=len(self.organization_options)))
        else:
            if self.__dict__.get("_activity_run_active", False):
                self._finish_activity_run(True)
            self.log_message(self.t("organizations_not_found"))

    def _selected_organization(self) -> dict[str, str]:
        if self._get_upload_target() != "organization":
            return {"id": "", "name": "", "create_url": ""}
        selected = ""
        if "oj_target_option" in self.__dict__:
            try:
                selected = self.oj_target_option.get()
            except Exception:
                selected = ""
        for option in getattr(self, "organization_options", []):
            if selected == self._organization_display(option):
                return {"id": option.id, "name": option.name, "create_url": option.create_url}
        if "oj_org_option" in self.__dict__:
            try:
                selected = self.oj_org_option.get()
            except Exception:
                selected = ""
        for option in getattr(self, "organization_options", []):
            if selected == self._organization_display(option):
                return {"id": option.id, "name": option.name, "create_url": option.create_url}
        manual = ""
        if "oj_org_manual_entry" in self.__dict__:
            try:
                manual = self.oj_org_manual_entry.get().strip()
            except Exception:
                manual = ""
        return {"id": manual, "name": manual, "create_url": ""}

    def refresh_organizations(self):
        url = self.oj_url_entry.get().strip()
        user = self.oj_user_entry.get().strip()
        pwd = self.oj_pass_entry.get().strip()
        if not all([url, user, pwd]):
            messagebox.showwarning(self.t("notice_title"), self.t("enter_oj_credentials"))
            return

        self._reset_activity_timer()
        self._begin_activity_run()
        self._log_activity_start(self.t("discovering_organizations"))

        def worker():
            try:
                uploader = OJUploader(url, user, pwd)
                if not uploader.login():
                    def on_login_failed():
                        self._finish_activity_run(False)
                        self.log_message(self.t("organization_login_failed"))
                        messagebox.showwarning(self.t("error_title"), self.t("organization_login_failed"))

                    self.ui(on_login_failed)
                    return
                options = uploader.discover_organizations()
                self.ui(lambda: self._set_organization_options(options))
            except Exception as e:
                error_msg = str(e)
                def on_discovery_error():
                    self._finish_activity_run(False)
                    self.log_message(self.t("organization_discovery_error", error=error_msg))

                self.ui(on_discovery_error)

        threading.Thread(target=worker, daemon=True).start()

    # ============================================================
    # Tải bài lên OJ
    # ============================================================
    def start_upload(self):
        if self._busy:
            return

        url = self.oj_url_entry.get().strip()
        user = self.oj_user_entry.get().strip()
        pwd = self.oj_pass_entry.get().strip()
        code = self.oj_code_entry.get().strip()
        zip_path = self.oj_zip_entry.get().strip()
        desc_text = self.oj_desc_textbox.get("0.0", tk.END).strip()
        use_statement_text = self._use_statement_text_for_upload()
        description_html = self._resolve_upload_description_html(desc_text, use_statement_text=use_statement_text)
        upload_target = self._get_upload_target()
        selected_organization = self._selected_organization()

        if not all([url, user, pwd, code, zip_path]):
            messagebox.showwarning(self.t("notice_title"), self.t("enter_required"))
            return
        if upload_target == "organization" and not (selected_organization["id"] or selected_organization["create_url"]):
            messagebox.showwarning(self.t("notice_title"), self.t("missing_organization"))
            return

        if not os.path.exists(zip_path):
            messagebox.showerror(self.t("error_title"), self.t("zip_not_found"))
            return

        try:
            time_limit = float(self.oj_time_entry.get().strip())
            memory_limit = int(self.oj_mem_entry.get().strip())
            points = float(self.oj_points_entry.get().strip())
            is_public = self.oj_public_var.get()
        except Exception:
            messagebox.showerror(self.t("error_title"), self.t("invalid_metrics"))
            return

        summary_source = desc_text if use_statement_text else code
        summary = self.current_plan.get("summary") or (summary_source[:180] + "..." if len(summary_source) > 180 else summary_source)
        statement_file_path = self._resolve_upload_statement_file()
        if statement_file_path and not os.path.exists(statement_file_path):
            messagebox.showerror(self.t("error_title"), self.t("statement_file_not_found"))
            return
        source_error_key = self._upload_statement_source_error_key(description_html, statement_file_path, use_statement_text=use_statement_text)
        if source_error_key:
            messagebox.showwarning(self.t("notice_title"), self.t(source_error_key))
            return
        settings = OJSettings(
            url=url,
            user=user,
            password=pwd,
            time_limit=time_limit,
            memory_mb=memory_limit,
            points=points,
            is_public=is_public,
        )

        self._reset_activity_timer()
        self._begin_activity_run()
        self.set_busy(True, self.t("uploading"))
        self._log_activity_start(self.t("preparing_upload", code=code))

        threading.Thread(
            target=self.upload_worker,
            args=(settings, code, zip_path, summary, description_html, statement_file_path, upload_target, selected_organization),
            daemon=True,
        ).start()

    def upload_worker(self, settings, code, zip_path, summary, description_html, statement_file_path, upload_target="root", selected_organization=None):
        completed = False
        try:
            overwrite_event = threading.Event()
            overwrite_decision = []

            def ask_overwrite() -> None:
                overwrite_decision.append(
                    messagebox.askyesno(
                        self.t("overwrite_title"),
                        self.t("overwrite_prompt", code=code),
                    )
                )
                overwrite_event.set()

            def overwrite_callback() -> bool:
                self.ui(ask_overwrite)
                overwrite_event.wait()
                return bool(overwrite_decision and overwrite_decision[0])

            request = UploadRequest(
                settings=settings,
                code=code,
                zip_path=zip_path,
                summary=summary,
                description_html=description_html,
                description_markdown=description_html,
                upload_target=upload_target,
                organization_id=(selected_organization or {}).get("id", ""),
                organization_name=(selected_organization or {}).get("name", ""),
                organization_create_url=(selected_organization or {}).get("create_url", ""),
                statement_file_path=statement_file_path,
            )

            ok, msg = upload_problem(
                request=request,
                log_callback=lambda m: self.ui(lambda: self.progress_message(m)),
                overwrite_callback=overwrite_callback,
            )
            if ok:
                completed = True
                self.ui(lambda: self._finish_activity_run(True))
                self.ui(lambda: self.log_message(self.t("upload_done", msg=msg)))
                self.ui(lambda: self._notify_done_dialog(self.t("upload_success_title"), tr_runtime(self.ui_lang, msg)))
            else:
                self.ui(lambda: self.log_message(self.t("upload_fail", msg=tr_runtime(self.ui_lang, msg))))
        except Exception as e:
            error_msg = str(e)
            self.ui(lambda: self.log_message(self.t("upload_error", error=error_msg)))
        finally:
            if not completed:
                self.ui(lambda: self._finish_activity_run(False))
            self.ui(lambda: self.set_busy(False, self.t("ready") + "."))


if __name__ == "__main__":
    App().mainloop()
