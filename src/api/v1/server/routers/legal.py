"""Public, localized legal pages for Telescan."""

from dataclasses import dataclass
from html import escape

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import HTMLResponse

__all__ = ["legal_router"]


@dataclass(frozen=True)
class LegalDocument:
    title: str
    summary: str
    effective_date: str
    sections: tuple[tuple[str, str], ...]


DOCUMENTS: dict[str, dict[str, LegalDocument]] = {
    "privacy": {
        "en": LegalDocument(
            title="Privacy Policy",
            summary=(
                "How Telescan processes account, profile-photo, and nearby "
                "discovery data — and how you stay in control."
            ),
            effective_date="Effective August 12, 2026",
            sections=(
                (
                    "Overview",
                    "<p>Telescan is an iOS app for discovering nearby users "
                    "and opening the public Telegram profiles they choose to "
                    "share. This policy applies to the Telescan app, Telegram "
                    "bot, API, database, and profile-photo storage.</p>",
                ),
                (
                    "Data we process",
                    "<p>When you register through the Telescan Telegram bot, "
                    "we receive your Telegram ID, first name, username, and "
                    "current public profile photo. The bot generates an "
                    "eight-character authentication code and stores only its "
                    "SHA-256 hash on the server. The original code may be "
                    "stored locally by the iOS app.</p>"
                    "<p>If you choose another profile photo, Telescan accesses "
                    "only the image selected through the camera or system photo "
                    "picker. The app resizes and compresses it before uploading "
                    "a copy to Telescan cloud storage.</p>"
                    "<ul><li>Telegram ID, first name, and username</li>"
                    "<li>Hashed authentication code</li>"
                    "<li>Telegram or user-selected profile photo</li></ul>",
                ),
                (
                    "Nearby discovery",
                    "<p>While discoverability is enabled, the app broadcasts "
                    "your Telegram ID over Bluetooth Low Energy. Nearby "
                    "Telescan devices use it to request the profile you share. "
                    "Signal strength and approximate distance are processed "
                    "locally and are not sent to the Telescan server.</p>",
                ),
                (
                    "Data we do not collect",
                    "<p>Telescan does not request or store GPS location, "
                    "contacts, Telegram messages, advertising identifiers, or "
                    "movement history. It does not include advertising or "
                    "third-party analytics SDKs.</p>",
                ),
                (
                    "Use and sharing",
                    "<p>Account data is used only to register users, display "
                    "shared profiles, manage profile photos, operate nearby "
                    "discovery, and maintain the service. Telescan does not "
                    "sell personal data.</p>"
                    "<p>Data is disclosed only to nearby users when you enable "
                    "discoverability, to infrastructure providers required to "
                    "operate the service, or when required by law.</p>",
                ),
                (
                    "Security and retention",
                    "<p>API traffic uses HTTPS. Authentication codes are "
                    "hashed before transmission and are stored on the server "
                    "only as hashes. Account records and stored profile photos "
                    "remain until you delete the Telescan account. Local data "
                    "remains until account deletion or removal of the app.</p>"
                    "<p>Standard request metadata such as IP address, time, "
                    "path, and response status may be processed for delivery, "
                    "reliability, and security — never for advertising or "
                    "behavioral analytics.</p>",
                ),
                (
                    "Account and data deletion",
                    "<p>Open your profile in the app, select <strong>Delete "
                    "account</strong>, and confirm. Telescan removes the live "
                    "account record, hashed authentication code, stored profile "
                    "photos, and local account data and caches. This operation "
                    "cannot be undone and does not affect your Telegram account.</p>",
                ),
                (
                    "Your choices",
                    "<p>You can disable discoverability, replace or remove your "
                    "profile photo, update the authentication code through the "
                    "bot, or delete your account. Depending on applicable law, "
                    "you may also have rights to access, correct, restrict, or "
                    "object to processing of personal data.</p>"
                    "<p>Telescan is not intended for children under 13. A higher "
                    "minimum age may apply where required by local law.</p>",
                ),
                (
                    "Changes and contact",
                    "<p>We may update this policy when the service or legal "
                    "requirements change. The effective date identifies the "
                    "current version.</p><p>Privacy questions: "
                    "<a href=\"mailto:admin@tgtelescan.ru\">"
                    "admin@tgtelescan.ru</a>.</p>",
                ),
            ),
        ),
        "ru": LegalDocument(
            title="Политика конфиденциальности",
            summary=(
                "Как Telescan обрабатывает данные аккаунта, фотографии и "
                "поиска людей рядом — и как вы ими управляете."
            ),
            effective_date="Действует с 12 августа 2026 года",
            sections=(
                (
                    "Общие положения",
                    "<p>Telescan — приложение для iOS, которое помогает "
                    "находить пользователей рядом и открывать публичные "
                    "профили Telegram, которыми они решили поделиться. "
                    "Политика распространяется на приложение, Telegram-бота, "
                    "API, базу данных и хранилище фотографий Telescan.</p>",
                ),
                (
                    "Какие данные мы обрабатываем",
                    "<p>При регистрации через Telegram-бота Telescan мы "
                    "получаем ваш Telegram ID, имя, username и текущую публичную "
                    "фотографию профиля. Бот создаёт восьмизначный код "
                    "аутентификации, а на сервере хранится только его SHA-256 "
                    "хеш. Исходный код может храниться локально в приложении.</p>"
                    "<p>Если вы выбираете другую фотографию, Telescan получает "
                    "доступ только к снимку, выбранному через камеру или "
                    "системный медиапикер. Приложение уменьшает и сжимает его "
                    "перед загрузкой копии в облачное хранилище.</p>"
                    "<ul><li>Telegram ID, имя и username</li>"
                    "<li>Хеш кода аутентификации</li>"
                    "<li>Фотография из Telegram или выбранная вами</li></ul>",
                ),
                (
                    "Поиск людей рядом",
                    "<p>Когда видимость включена, приложение передаёт ваш "
                    "Telegram ID через Bluetooth Low Energy. Устройства Telescan "
                    "рядом используют его, чтобы запросить опубликованный вами "
                    "профиль. Сила сигнала и примерное расстояние обрабатываются "
                    "локально и не отправляются на сервер Telescan.</p>",
                ),
                (
                    "Что мы не собираем",
                    "<p>Telescan не запрашивает и не хранит GPS-геолокацию, "
                    "контакты, сообщения Telegram, рекламные идентификаторы или "
                    "историю перемещений. В приложении нет рекламы и сторонних "
                    "аналитических SDK.</p>",
                ),
                (
                    "Использование и передача",
                    "<p>Данные аккаунта используются только для регистрации, "
                    "показа опубликованных профилей, управления фотографиями, "
                    "поиска людей рядом и поддержки сервиса. Telescan не продаёт "
                    "персональные данные.</p>"
                    "<p>Данные раскрываются только пользователям рядом при "
                    "включённой видимости, поставщикам инфраструктуры для работы "
                    "сервиса или когда этого требует закон.</p>",
                ),
                (
                    "Безопасность и хранение",
                    "<p>API работает через HTTPS. Коды аутентификации хешируются "
                    "до отправки и хранятся на сервере только в виде хешей. "
                    "Запись аккаунта и фотографии хранятся до удаления аккаунта "
                    "Telescan. Локальные данные остаются до удаления аккаунта "
                    "или приложения.</p>"
                    "<p>Стандартные данные запросов — IP-адрес, время, путь и "
                    "статус ответа — могут обрабатываться для доставки, "
                    "надёжности и безопасности, но не для рекламы или "
                    "поведенческой аналитики.</p>",
                ),
                (
                    "Удаление аккаунта и данных",
                    "<p>Откройте профиль в приложении, выберите <strong>Удалить "
                    "аккаунт</strong> и подтвердите действие. Telescan удалит "
                    "активную запись аккаунта, хеш кода, сохранённые фотографии, "
                    "локальные данные и кеши. Операцию нельзя отменить; аккаунт "
                    "Telegram при этом не изменяется.</p>",
                ),
                (
                    "Ваш выбор",
                    "<p>Вы можете отключить видимость, заменить или удалить "
                    "фотографию, обновить код через бота или удалить аккаунт. "
                    "В зависимости от применимого законодательства вы также "
                    "можете иметь право на доступ, исправление, ограничение или "
                    "возражение против обработки персональных данных.</p>"
                    "<p>Telescan не предназначен для детей младше 13 лет. "
                    "Местное законодательство может устанавливать более высокий "
                    "минимальный возраст.</p>",
                ),
                (
                    "Изменения и контакты",
                    "<p>Мы можем обновлять политику при изменении сервиса или "
                    "правовых требований. Дата вступления в силу обозначает "
                    "текущую версию.</p><p>Вопросы о конфиденциальности: "
                    "<a href=\"mailto:admin@tgtelescan.ru\">"
                    "admin@tgtelescan.ru</a>.</p>",
                ),
            ),
        ),
    },
    "terms": {
        "en": LegalDocument(
            title="Terms of Service",
            summary=(
                "The essential terms for using the Telescan app, bot, API, "
                "and related services."
            ),
            effective_date="Effective August 12, 2026",
            sections=(
                (
                    "Agreement",
                    "<p>These Terms govern your use of the Telescan iOS app, "
                    "Telegram bot, API, and related services. By continuing in "
                    "the app or using the service, you agree to these Terms and "
                    "the <a href=\"/privacy\">Privacy Policy</a>. If you do not "
                    "agree, do not use Telescan.</p>",
                ),
                (
                    "The service",
                    "<p>Telescan helps nearby users discover and open public "
                    "Telegram profiles they choose to share. Bluetooth Low "
                    "Energy provides local discovery; an internet connection is "
                    "required for registration, profile loading, photo "
                    "management, and account deletion.</p>"
                    "<p>Telescan is experimental. BLE visibility and distance "
                    "estimates may be delayed, incomplete, or inaccurate and "
                    "must not be used for safety, navigation, emergencies, "
                    "identity verification, or decisions requiring precise "
                    "proximity.</p>",
                ),
                (
                    "Your account and content",
                    "<p>You must be allowed to use Telegram and Telescan under "
                    "applicable law and platform rules. You are responsible for "
                    "your authentication code, Telegram account, profile "
                    "information, and uploaded photos. Share only content you "
                    "have the right to use.</p>"
                    "<p>Your profile is available to nearby users only while "
                    "discoverability is enabled, although radio identifiers can "
                    "be observed or replayed by devices in range.</p>",
                ),
                (
                    "Acceptable use",
                    "<p>Do not use Telescan to:</p><ul>"
                    "<li>Harass, stalk, threaten, impersonate, deceive, or harm</li>"
                    "<li>Collect, publish, or misuse another person’s data</li>"
                    "<li>Upload unlawful or rights-infringing content</li>"
                    "<li>Probe, disrupt, overload, bypass, or interfere with the service</li>"
                    "<li>Use automation or reverse engineering unlawfully</li>"
                    "</ul><p>We may restrict access when reasonably necessary to "
                    "protect users, the service, or comply with law.</p>",
                ),
                (
                    "Third-party services",
                    "<p>Telescan relies on Telegram, Apple platforms, and "
                    "infrastructure providers. Their services and terms are "
                    "separate from ours. App Store distributions are also "
                    "subject to Apple’s <a href=\"https://www.apple.com/legal/"
                    "internet-services/itunes/dev/stdeula/\" rel=\"noopener\">"
                    "Standard Licensed Application EULA</a> unless another "
                    "agreement applies.</p>",
                ),
                (
                    "Availability and warranties",
                    "<p>The service may change, be suspended, or stop operating. "
                    "To the maximum extent permitted by law, Telescan is "
                    "provided <strong>as is</strong> and <strong>as available</strong> "
                    "without guarantees of uninterrupted availability, "
                    "compatibility, accuracy, security, or fitness for a "
                    "particular purpose. Mandatory consumer rights remain "
                    "unaffected.</p>",
                ),
                (
                    "Limitation of liability",
                    "<p>To the maximum extent permitted by law, Telescan’s "
                    "maintainers are not liable for indirect, incidental, "
                    "special, or consequential loss arising from use of or "
                    "inability to use the service. Liability that cannot be "
                    "excluded remains limited only as permitted by law.</p>",
                ),
                (
                    "Changes and contact",
                    "<p>We may update these Terms when the service or legal "
                    "requirements change. Material changes will be presented "
                    "through an appropriate service or documentation update.</p>"
                    "<p>Questions: <a href=\"mailto:admin@tgtelescan.ru\">"
                    "admin@tgtelescan.ru</a>.</p>",
                ),
            ),
        ),
        "ru": LegalDocument(
            title="Условия использования",
            summary=(
                "Основные условия использования приложения Telescan, бота, "
                "API и связанных сервисов."
            ),
            effective_date="Действуют с 12 августа 2026 года",
            sections=(
                (
                    "Согласие с условиями",
                    "<p>Эти Условия регулируют использование приложения "
                    "Telescan для iOS, Telegram-бота, API и связанных сервисов. "
                    "Продолжая работу в приложении или используя сервис, вы "
                    "принимаете эти Условия и <a href=\"/privacy?lang=ru\">"
                    "Политику конфиденциальности</a>. Если вы не согласны, не "
                    "используйте Telescan.</p>",
                ),
                (
                    "Сервис",
                    "<p>Telescan помогает пользователям рядом находить и "
                    "открывать публичные профили Telegram, которыми они решили "
                    "поделиться. Bluetooth Low Energy используется для поиска; "
                    "интернет требуется для регистрации, загрузки профилей, "
                    "управления фотографиями и удаления аккаунта.</p>"
                    "<p>Telescan является экспериментальным сервисом. Видимость "
                    "BLE и оценка расстояния могут быть неточными, неполными или "
                    "запаздывать. Их нельзя использовать для безопасности, "
                    "навигации, экстренной помощи, проверки личности или решений, "
                    "требующих точного расстояния.</p>",
                ),
                (
                    "Ваш аккаунт и контент",
                    "<p>Вы должны иметь право использовать Telegram и Telescan "
                    "по применимым законам и правилам платформ. Вы отвечаете за "
                    "код аутентификации, аккаунт Telegram, сведения профиля и "
                    "загруженные фотографии. Публикуйте только контент, на "
                    "использование которого у вас есть права.</p>"
                    "<p>Профиль доступен пользователям рядом только при "
                    "включённой видимости, однако радиоидентификаторы могут быть "
                    "перехвачены или повторены устройствами в зоне сигнала.</p>",
                ),
                (
                    "Допустимое использование",
                    "<p>Запрещено использовать Telescan, чтобы:</p><ul>"
                    "<li>Преследовать, запугивать, выдавать себя за другого или причинять вред</li>"
                    "<li>Собирать, публиковать или неправомерно использовать чужие данные</li>"
                    "<li>Загружать незаконный контент или нарушать чужие права</li>"
                    "<li>Исследовать, нарушать, перегружать или обходить защиту сервиса</li>"
                    "<li>Незаконно применять автоматизацию или обратную разработку</li>"
                    "</ul><p>Мы можем ограничить доступ, когда это обоснованно "
                    "необходимо для защиты пользователей, сервиса или соблюдения закона.</p>",
                ),
                (
                    "Сторонние сервисы",
                    "<p>Telescan зависит от Telegram, платформ Apple и "
                    "поставщиков инфраструктуры. Их сервисы и условия не "
                    "являются частью наших. Приложение из App Store также "
                    "подчиняется <a href=\"https://www.apple.com/legal/internet-"
                    "services/itunes/dev/stdeula/\" rel=\"noopener\">стандартному "
                    "лицензионному соглашению Apple</a>, если не применяется "
                    "другое соглашение.</p>",
                ),
                (
                    "Доступность и гарантии",
                    "<p>Сервис может измениться, быть приостановлен или "
                    "прекратить работу. В максимально разрешённой законом "
                    "степени Telescan предоставляется <strong>как есть</strong> и "
                    "<strong>по мере доступности</strong>, без гарантий "
                    "бесперебойной работы, совместимости, точности, безопасности "
                    "или пригодности для конкретной цели. Обязательные права "
                    "потребителей сохраняются.</p>",
                ),
                (
                    "Ограничение ответственности",
                    "<p>В максимально разрешённой законом степени разработчики "
                    "Telescan не отвечают за косвенные, случайные, специальные "
                    "или последующие убытки из-за использования или невозможности "
                    "использования сервиса. Ответственность, которую нельзя "
                    "исключить, ограничивается только в разрешённой законом степени.</p>",
                ),
                (
                    "Изменения и контакты",
                    "<p>Мы можем обновлять Условия при изменении сервиса или "
                    "правовых требований. О существенных изменениях будет "
                    "сообщено через сервис или документацию.</p><p>Вопросы: "
                    "<a href=\"mailto:admin@tgtelescan.ru\">"
                    "admin@tgtelescan.ru</a>.</p>",
                ),
            ),
        ),
    },
}


legal_router = APIRouter(tags=["legal"], include_in_schema=False)


def resolve_language(requested: str | None, accept_language: str) -> str:
    if requested:
        normalized = requested.strip().lower()
        if normalized.startswith("ru"):
            return "ru"
        if normalized.startswith("en"):
            return "en"

    preferences: list[tuple[float, str]] = []
    for item in accept_language.lower().split(","):
        parts = [part.strip() for part in item.split(";")]
        language = parts[0]
        if not language.startswith(("ru", "en")):
            continue

        quality = 1.0
        for parameter in parts[1:]:
            if parameter.startswith("q="):
                try:
                    quality = float(parameter[2:])
                except ValueError:
                    quality = 0.0

        preferences.append((quality, "ru" if language.startswith("ru") else "en"))

    return max(preferences, default=(0.0, "en"))[1]


def render_page(kind: str, language: str) -> str:
    document = DOCUMENTS[kind][language]
    other_kind = "terms" if kind == "privacy" else "privacy"
    other_document = DOCUMENTS[other_kind][language]
    opposite_language = "ru" if language == "en" else "en"
    language_name = "Русский" if language == "en" else "English"
    current_label = "Privacy" if kind == "privacy" else "Terms"
    other_label = "Terms" if kind == "privacy" else "Privacy"
    if language == "ru":
        current_label = "Конфиденциальность" if kind == "privacy" else "Условия"
        other_label = "Условия" if kind == "privacy" else "Конфиденциальность"

    sections = "".join(
        f'<section><h2>{escape(title)}</h2>{body}</section>'
        for title, body in document.sections
    )

    return f"""<!doctype html>
<html lang="{language}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0a84ff">
  <meta name="description" content="{escape(document.summary)}">
  <link rel="canonical" href="https://tgtelescan.ru/{kind}">
  <title>{escape(document.title)} · Telescan</title>
  <style>
    :root {{ color-scheme: light dark; --brand:#0a84ff; --ink:#102033;
      --muted:#5d6b7c; --page:#f3f7fc; --card:rgba(255,255,255,.86);
      --line:rgba(19,51,84,.12); --shadow:0 22px 65px rgba(28,77,126,.12); }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{ margin:0; font:16px/1.68 -apple-system,BlinkMacSystemFont,"SF Pro Text",
      "Segoe UI",sans-serif; color:var(--ink); background:var(--page); }}
    body::before {{ content:""; position:fixed; inset:0; pointer-events:none;
      background:radial-gradient(circle at 12% -10%,rgba(10,132,255,.24),transparent 38%),
      radial-gradient(circle at 92% 8%,rgba(105,190,255,.18),transparent 32%); }}
    a {{ color:var(--brand); text-underline-offset:3px; }}
    .shell {{ position:relative; width:min(100% - 32px,900px); margin:auto; }}
    header {{ padding:22px 0 10px; }}
    nav {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
    .brand {{ margin-right:auto; color:var(--ink); font-weight:750; font-size:18px; }}
    .nav-link,.language {{ padding:7px 11px; border:1px solid var(--line);
      border-radius:999px; color:var(--muted); background:var(--card);
      text-decoration:none; font-size:13px; font-weight:650; backdrop-filter:blur(16px); }}
    .nav-link[aria-current="page"] {{ color:#fff; border-color:var(--brand); background:var(--brand); }}
    .hero {{ padding:70px 0 42px; text-align:center; }}
    h1 {{ max-width:760px; margin:0 auto; font-size:clamp(40px,8vw,68px); line-height:1.02;
      letter-spacing:-.05em; }}
    .summary {{ max-width:650px; margin:22px auto 16px; color:var(--muted);
      font-size:clamp(17px,2.5vw,21px); line-height:1.55; }}
    .date {{ display:inline-block; padding:7px 12px; border-radius:999px;
      color:var(--muted); background:rgba(10,132,255,.08); font-size:13px; font-weight:650; }}
    article {{ padding:clamp(25px,6vw,64px); border:1px solid var(--line); border-radius:28px;
      background:var(--card); box-shadow:var(--shadow); backdrop-filter:blur(24px); }}
    section + section {{ margin-top:42px; padding-top:38px; border-top:1px solid var(--line); }}
    h2 {{ margin:0 0 14px; font-size:clamp(23px,4vw,30px); line-height:1.2;
      letter-spacing:-.025em; }}
    p {{ margin:12px 0; }}
    ul {{ margin:14px 0; padding-left:22px; }}
    li {{ margin:7px 0; padding-left:4px; }}
    footer {{ display:flex; justify-content:space-between; gap:18px; padding:32px 4px 48px;
      color:var(--muted); font-size:13px; }}
    footer a {{ color:inherit; }}
    @media (max-width:620px) {{ .shell {{ width:min(100% - 22px,900px); }}
      header {{ padding-top:14px; }} .brand {{ width:100%; margin-bottom:4px; }}
      .hero {{ padding:48px 10px 32px; }} article {{ border-radius:22px; }}
      footer {{ flex-direction:column; }} }}
    @media (prefers-color-scheme:dark) {{ :root {{ --ink:#edf6ff; --muted:#a8b7c8;
      --page:#10161d; --card:rgba(24,33,43,.86); --line:rgba(180,216,255,.12);
      --shadow:0 24px 75px rgba(0,0,0,.3); }} body::before {{
      background:radial-gradient(circle at 12% -10%,rgba(10,132,255,.3),transparent 38%),
      radial-gradient(circle at 92% 8%,rgba(24,73,120,.28),transparent 32%); }} }}
    @media print {{ header,footer {{ display:none; }} body {{ background:#fff; }}
      body::before {{ display:none; }} .hero {{ padding:20px 0; }} article {{ box-shadow:none; }} }}
  </style>
</head>
<body>
  <div class="shell">
    <header><nav aria-label="Legal documents">
      <span class="brand">Telescan</span>
      <a class="nav-link" aria-current="page" href="/{kind}?lang={language}">{current_label}</a>
      <a class="nav-link" href="/{other_kind}?lang={language}">{other_label}</a>
      <a class="language" href="/{kind}?lang={opposite_language}" hreflang="{opposite_language}">{language_name}</a>
    </nav></header>
    <main>
      <div class="hero"><h1>{escape(document.title)}</h1>
        <p class="summary">{escape(document.summary)}</p>
        <span class="date">{escape(document.effective_date)}</span></div>
      <article>{sections}</article>
    </main>
    <footer><span>© 2026 Telescan</span><span>
      <a href="/{other_kind}?lang={language}">{escape(other_document.title)}</a> ·
      <a href="mailto:admin@tgtelescan.ru">Contact</a></span></footer>
  </div>
</body>
</html>"""


def page_response(kind: str, language: str) -> HTMLResponse:
    return HTMLResponse(
        content=render_page(kind, language),
        status_code=status.HTTP_200_OK,
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Language": language,
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "img-src 'self' data:; base-uri 'none'; form-action 'none'; "
                "frame-ancestors 'none'"
            ),
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Vary": "Accept-Language",
            "X-Content-Type-Options": "nosniff",
        },
    )


@legal_router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy(
    request: Request,
    lang: str | None = Query(default=None, max_length=10),
) -> HTMLResponse:
    language = resolve_language(lang, request.headers.get("accept-language", ""))
    return page_response("privacy", language)


@legal_router.get("/terms", response_class=HTMLResponse)
async def terms_of_service(
    request: Request,
    lang: str | None = Query(default=None, max_length=10),
) -> HTMLResponse:
    language = resolve_language(lang, request.headers.get("accept-language", ""))
    return page_response("terms", language)
