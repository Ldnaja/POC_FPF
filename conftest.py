import logging
import re
import time
import pytest
from playwright.sync_api import sync_playwright, Page, expect, TimeoutError as PwTimeoutError

HOME_URL = "https://fpftech.com/"
CASES_URL = "https://fpftech.com/cases-de-sucesso/"
CONTACT_URL = "https://fpftech.com/contato/"
BLOG_URL = "https://fpftech.com/blog/"

EXPECTED_UEA_FIRST_TITLE = (
    "FPFtech e UEA vencem e fazem de Manaus a sede da 36ª Conferência Anprotec em 2026"
)

RE_SPACES = re.compile(r"\s+")
RE_NOTICIAS = re.compile(r"not[ií]cias", re.I)
RE_CASES = re.compile(r"cases\s+de\s+sucesso", re.I)

# ============================
# Logger
# ============================

class FPFLogger:
    @staticmethod
    def _configure_logger() -> logging.Logger:
        logger = logging.getLogger("FPF_POC_Logger")
        logger.setLevel(logging.DEBUG)

        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)

        return logger

    def __init__(self, test_id: str) -> None:
        self.test_id = test_id
        self.logger = self._configure_logger()

    def log(self, message: str, level: str = "info") -> None:
        lvl = (level or "info").lower()
        prefix = f"[FPF POC][{self.test_id}][{lvl.upper()}] "
        fn = getattr(self.logger, lvl, self.logger.info)
        fn(prefix + message)


@pytest.fixture
def tlog(request) -> FPFLogger:
    raw = str(request.node.name).split("[", 1)[0]
    if raw.startswith("test_"):
        test_id = raw.replace("test_", "TEST_", 1).upper()
    else:
        test_id = raw.upper()
    return FPFLogger(test_id)


# ============================
# Fixtures Playwright
# ============================

@pytest.fixture(scope="session")
def pw():
    p = sync_playwright().start()
    try:
        yield p
    finally:
        p.stop()


@pytest.fixture(scope="session")
def browser(pw, request):
    headed = bool(request.config.getoption("--headed", default=False))
    slowmo = int(request.config.getoption("--slowmo", default=0) or 0)

    b = pw.chromium.launch(
        headless=not headed,
        slow_mo=slowmo,
        args=["--window-size=1920,1080"],
    )
    try:
        yield b
    finally:
        b.close()


@pytest.fixture
def page(browser) -> Page:  # type: ignore
    context = browser.new_context(viewport={"width": 1920, "height": 1080})
    p = context.new_page()
    try:
        yield p
    finally:
        context.close()


# ============================
# Helpers
# ============================

def norm(s: str) -> str:
    return RE_SPACES.sub(" ", (s or "").strip())


def goto(page: Page, url: str, *, wait: str = "domcontentloaded") -> None:
    page.goto(url, wait_until=wait)


def click_or_goto(locator, fallback_url: str, page: Page, timeout_ms: int = 3000) -> None:
    href = None
    try:
        href = locator.get_attribute("href")
    except Exception:
        pass

    try:
        locator.click(timeout=timeout_ms)
        return
    except PwTimeoutError:
        try:
            locator.click(timeout=timeout_ms, force=True)
            return
        except PwTimeoutError:
            page.goto(href or fallback_url, wait_until="domcontentloaded")


# ============================
# 0001 - Cases
# ============================

def open_cases_page(page: Page) -> None:
    # abre home rápido
    goto(page, HOME_URL, wait="domcontentloaded")

    link = page.get_by_role("link", name=RE_CASES).first

    if link.count() > 0:
        try:
            link.scroll_into_view_if_needed()

            # clique "rápido" (não deixa o Playwright tentar 30s na HOME)
            try:
                link.click(timeout=2500, no_wait_after=True)
            except PwTimeoutError:
                link.click(timeout=2500, force=True, no_wait_after=True)

            # espera a URL mudar (bem mais confiável que networkidle)
            try:
                page.wait_for_url(re.compile(r".*/cases-de-sucesso/?"), timeout=8000)
            except Exception:
                # se não navegou, vai direto
                goto(page, CASES_URL, wait="domcontentloaded")

        except Exception:
            goto(page, CASES_URL, wait="domcontentloaded")
    else:
        goto(page, CASES_URL, wait="domcontentloaded")

    # valida que chegou
    expect(page.get_by_role("heading", name=RE_CASES)).to_be_visible(timeout=15000)


def pick_selectors(page: Page) -> tuple[str, str]:
    card_candidates = [
        "article.elementor-post",
        ".elementor-posts-container article",
        ".elementor-posts article",
        "article",
    ]
    title_candidates = [
        "article.elementor-post .elementor-post__title",
        ".elementor-posts-container .elementor-post__title",
        ".elementor-post__title",
        "article h3",
    ]
    card_sel = next((s for s in card_candidates if page.locator(s).count() > 0), "article")
    title_sel = next((s for s in title_candidates if page.locator(s).count() > 0), "article h3")
    return card_sel, title_sel


def click_load_more_until_end(page: Page, card_selector: str, max_clicks: int = 50) -> None:
    load_more = page.get_by_role("button", name=re.compile(r"carregar\s+mais", re.I))

    for _ in range(max_clicks):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)

        try:
            if not load_more.is_visible(timeout=1500):
                return
        except Exception:
            return

        prev = page.locator(card_selector).count()
        load_more.scroll_into_view_if_needed()
        load_more.click()
        page.wait_for_load_state("networkidle")

        for _ in range(32):  # ~8s
            page.wait_for_timeout(250)
            if page.locator(card_selector).count() > prev:
                break
        else:
            return


def extract_case_titles(page: Page, title_selector: str) -> list[str]:
    raw = page.locator(title_selector).all_inner_texts()
    titles: list[str] = []
    seen: set[str] = set()

    for t in raw:
        t = norm(t)
        if t and t not in seen:
            seen.add(t)
            titles.append(t)
    return titles


def log_titles(tlog: FPFLogger, titles: list[str]) -> None:
    tlog.log("===== CASES =====")
    for i, title in enumerate(titles, start=1):
        tlog.log(f"{i:04d} | {title}")
    tlog.log("=====================================")
    tlog.log(f"TOTAL: {len(titles)}")


# ============================
# 0002 - Contato
# ============================

def open_contact_page_via_fale_com_a_gente(page: Page) -> None:
    goto(page, HOME_URL)

    btn_talk = page.locator("a[href*='/contato/']").filter(
        has_text=re.compile(r"fale\s+com\s+a\s+gente", re.I)
    ).first

    if btn_talk.count() > 0:
        try:
            btn_talk.scroll_into_view_if_needed()
            expect(btn_talk).to_be_visible(timeout=3000)
            btn_talk.click()
            page.wait_for_load_state("networkidle")
        except Exception:
            page.goto(CONTACT_URL, wait_until="networkidle")
    else:
        page.goto(CONTACT_URL, wait_until="networkidle")

    expect(page.get_by_role("heading", name=re.compile(r"fale\s+com\s+a\s+fpftech", re.I))).to_be_visible(timeout=15000)


def fill_contact_form_without_submit(
    page: Page,
    nome: str,
    email: str,
    empresa: str,
    telefone: str,
    mensagem: str,
) -> None:
    page.locator("input#form-field-name").fill(nome)
    page.locator("input#form-field-email").fill(email)
    page.locator("input#form-field-field_b131001").fill(empresa)
    page.locator("input#form-field-field_01c4f3f").fill(telefone)

    msg = page.locator(
        "textarea#form-field-message, textarea[name*='message'], textarea[name*='mensagem'], textarea"
    ).first
    msg.fill(mensagem)

    expect(page.get_by_role("button", name=re.compile(r"enviar", re.I))).to_be_visible(timeout=15000)


def extract_contact_info_from_sections(page: Page) -> dict:
    h_onde = page.locator(":is(h1,h2,h3,h4,h5,h6):has-text('Onde estamos')").first
    h_cont = page.locator(":is(h1,h2,h3,h4,h5,h6):has-text('Contatos')").first

    expect(h_onde).to_be_visible(timeout=20000)
    h_onde.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    expect(h_cont).to_be_visible(timeout=20000)

    def container_text(h) -> str:
        for xp in [
            "xpath=ancestor::*[contains(@class,'e-con')][1]",
            "xpath=ancestor::*[contains(@class,'elementor-element')][1]",
        ]:
            loc = h.locator(xp)
            if loc.count() > 0:
                try:
                    txt = loc.inner_text().strip()
                    if txt:
                        return txt
                except Exception:
                    pass

        p = h.locator("xpath=following::p[1]")
        if p.count() > 0:
            try:
                return p.inner_text().strip()
            except Exception:
                pass
        return ""

    onde_text = container_text(h_onde)
    cont_text = container_text(h_cont)
    combined = f"{onde_text}\n{cont_text}"

    emails = sorted(set(re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", combined, flags=re.I)))
    phones = sorted(set(re.findall(r"(?:\+\s*\d{1,3}\s*)?\(?\d{2}\)?\s*\d{4,5}\s*\d{4}", combined)))

    address = None
    for ln in [x.strip() for x in onde_text.splitlines() if x.strip()]:
        if ("Av." in ln or "Avenida" in ln or "Governador" in ln) and ("Manaus" in ln or "AM" in ln or "CEP" in ln):
            address = ln
            break
    if not address:
        for ln in [x.strip() for x in onde_text.splitlines() if x.strip()]:
            if "CEP" in ln:
                address = ln
                break

    return {"phones": phones, "emails": emails, "address": address}


def log_contact_info(tlog: FPFLogger, info: dict) -> None:
    tlog.log("===== CONTATO =====")

    tlog.log("Telefones:")
    if info.get("phones"):
        for p in info["phones"]:
            tlog.log(f" - {p}")
    else:
        tlog.log(" - (nenhum)")

    tlog.log("Emails:")
    if info.get("emails"):
        for e in info["emails"]:
            tlog.log(f" - {e}")
    else:
        tlog.log(" - (nenhum)")

    tlog.log("Endereço:")
    tlog.log(f" - {info.get('address') or '(não encontrado)'}")

    tlog.log("=====================================")


# ============================
# 0003 - Carrossel da home
# ============================

def open_home_page(page: Page) -> None:
    goto(page, HOME_URL, wait="domcontentloaded")
    page.wait_for_load_state("networkidle")

    page.mouse.wheel(0, 700)
    page.wait_for_timeout(350)


def _get_main_carousel(page: Page):
    carousel = page.locator(
        ".e-n-carousel",
        has_text=re.compile(
            r"Educação|Gestão\s+corporativa|Compromisso\s+social|Tecnologias\s+assistivas", re.I
        ),
    ).first

    expect(carousel).to_have_count(1, timeout=20000)
    carousel.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    expect(carousel).to_have_class(re.compile(r"swiper-initialized"), timeout=20000)
    return carousel


def _get_carousel_widget_scope(page: Page):
    carousel = _get_main_carousel(page)
    scope = carousel.locator("xpath=ancestor::*[contains(@class,'elementor-widget-container')][1]")
    if scope.count() == 0:
        scope = carousel.locator("xpath=ancestor::*[contains(@class,'elementor-widget')][1]")
    expect(scope).to_be_visible(timeout=20000)
    return scope


def _extract_slide_text(slide) -> dict:
    title = ""
    desc = ""

    h = slide.locator("h2, h3, h4").first
    if h.count() > 0:
        try:
            title = norm(h.inner_text())
        except Exception:
            pass

    try:
        ps = slide.locator("p").all_inner_texts()
        desc = " ".join(norm(x) for x in ps if norm(x))
    except Exception:
        desc = ""

    if not title and not desc:
        try:
            return {"title": "", "description": "", "raw": norm(slide.inner_text())}
        except Exception:
            return {"title": "", "description": "", "raw": ""}

    return {"title": title, "description": desc, "raw": ""}


def get_active_carousel_block_info(page: Page) -> dict:
    carousel = _get_main_carousel(page)

    slide = carousel.locator(".swiper-slide:not([aria-hidden='true'])").first
    if slide.count() == 0:
        slide = carousel.locator(".swiper-slide-active").first
    if slide.count() == 0:
        slide = carousel.locator(".swiper-slide").first

    expect(slide).to_be_visible(timeout=20000)
    return _extract_slide_text(slide)


def carousel_next(page: Page) -> None:
    scope = _get_carousel_widget_scope(page)
    btn = scope.locator(".elementor-swiper-button-next").first
    btn.scroll_into_view_if_needed()
    btn.click()


def collect_all_carousel_titles_via_next(page: Page, max_steps: int = 25) -> list[str]:
    _get_main_carousel(page)

    titles: list[str] = []
    seen: set[str] = set()

    cur = get_active_carousel_block_info(page).get("title", "").strip()
    if cur:
        titles.append(cur)
        seen.add(cur)

    for _ in range(max_steps):
        carousel_next(page)
        page.wait_for_timeout(650)

        t = get_active_carousel_block_info(page).get("title", "").strip()
        if not t:
            continue
        if t in seen:
            break
        titles.append(t)
        seen.add(t)

    return titles


def log_carousel_titles(tlog: FPFLogger, titles: list[str]) -> None:
    tlog.log("===== HOME CARROSSEL =====")
    for i, t in enumerate(titles, start=1):
        tlog.log(f"{i:04d} | {t}")
    tlog.log("========================================")
    tlog.log(f"TOTAL: {len(titles)}")


# ============================
# 0004 - Notícias (busca)
# ============================

def open_news_page_via_menu(page: Page) -> None:
    if page.url == "about:blank" or "fpftech.com" not in page.url:
        goto(page, HOME_URL)

    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(150)

    noticias = page.locator("a[href*='/blog']").filter(has_text=RE_NOTICIAS).first
    if noticias.count() == 0:
        page.goto(BLOG_URL, wait_until="domcontentloaded")
    else:
        click_or_goto(noticias, BLOG_URL, page)

    expect(page).to_have_url(re.compile(r".*/blog/?"), timeout=20000)


def _get_news_search_input(page: Page):
    container = page.locator("div.asl_w_container").first
    expect(container).to_be_visible(timeout=20000)

    inp = container.locator(
        "input[type='search'], input[type='text'], input.asl_text, input.asl-search"
    ).first
    expect(inp).to_be_visible(timeout=20000)
    return inp


def search_news_and_collect_titles(page: Page, query: str) -> list[str]:
    search_input = _get_news_search_input(page)
    search_input.click()
    search_input.fill(query)
    search_input.press("Enter")

    results_box = page.locator("div.asl_results").first
    try:
        results_box.wait_for(state="visible", timeout=2500)
        raw = page.locator(
            "div.asl_results div.asl_r h3, "
            "div.asl_results div.asl_r a span, "
            "div.asl_results div.asl_r a"
        ).all_text_contents()
        clean = [norm(t) for t in raw if norm(t) and len(norm(t)) > 3]
        return clean
    except Exception:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass

        h1 = page.locator("h1").first
        if h1.count() > 0:
            try:
                t = norm(h1.inner_text())
                if t:
                    return [t]
            except Exception:
                pass

        raw = page.locator("article h2, article h3, .elementor-post__title, .entry-title").all_text_contents()
        clean = [norm(t) for t in raw if norm(t) and len(norm(t)) > 3]
        return clean


def log_news_search(tlog: FPFLogger, term: str, titles: list[str]) -> None:
    tlog.log(f"===== NOTÍCIAS | busca: {term} =====")
    if not titles:
        tlog.log("(nenhum resultado)")
    else:
        for i, t in enumerate(titles, start=1):
            tlog.log(f"{i:04d} | {t}")
    tlog.log("====================================")


def assert_first_news_title_is_uea(page: Page, titles: list[str]) -> None:
    assert titles, f"Busca por 'UEA' não retornou títulos. URL atual: {page.url}"
    first = titles[0]
    assert EXPECTED_UEA_FIRST_TITLE in first, (
        "O primeiro resultado/título não é o esperado.\n"
        f"Esperado conter: {EXPECTED_UEA_FIRST_TITLE}\n"
        f"Recebido: {first}\n"
        f"URL atual: {page.url}"
    )
