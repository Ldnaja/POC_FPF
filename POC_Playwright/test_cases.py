from playwright.sync_api import Page

from conftest import *


def test_0001(page: Page, tlog):
    open_cases_page(page)

    card_sel, title_sel = pick_selectors(page)
    click_load_more_until_end(page, card_sel)

    titles = extract_case_titles(page, title_sel)
    log_titles(tlog, titles)

    assert len(titles) > 0, "Nenhum título de case foi encontrado"


def test_0002(page: Page, tlog):
    open_contact_page_via_fale_com_a_gente(page)

    fill_contact_form_without_submit(
        page=page,
        nome="Teste Playwright",
        email="teste@teste.com",
        empresa="Minha Empresa",
        telefone="92999999999",
        mensagem="POC Playwright",
    )

    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(800)

    info = extract_contact_info_from_sections(page)
    log_contact_info(tlog, info)

    assert (
        info["emails"] or info["phones"] or info["address"]
    ), "Não conseguiu extrair dados de contato das seções"


def test_0003(page: Page, tlog):
    open_home_page(page)

    titles = collect_all_carousel_titles_via_next(page, max_steps=25)
    log_carousel_titles(tlog, titles)

    assert len(titles) > 0, "Não conseguiu coletar títulos do carrossel"


def test_0004(page: Page, tlog):
    open_news_page_via_menu(page)

    titles = search_news_and_collect_titles(page, "UEA")
    log_news_search(tlog, "UEA", titles)

    assert_first_news_title_is_uea(page, titles)
