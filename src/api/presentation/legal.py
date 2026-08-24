"""Public, localized legal pages for Telescan."""

from dataclasses import dataclass
from functools import lru_cache
from html import escape
from pathlib import Path
from string import Template

__all__ = ["render_page", "resolve_language"]


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
                "How Telescan processes account, profile, and nearby "
                "discovery data — and how you stay in control."
            ),
            effective_date="Effective August 24, 2026",
            sections=(
                (
                    "Overview",
                    "<p>Telescan is an iOS app for discovering nearby users "
                    "and opening the public Telegram profiles they choose to "
                    "share. This policy applies to the Telescan app, Telegram "
                    "bot, API, and supporting service providers.</p>",
                ),
                (
                    "Data we process",
                    "<p>When you register through the Telescan Telegram bot, "
                    "we receive your Telegram ID, first name, username, and "
                    "current public profile photo. At your request, the API "
                    "issues a short-lived, one-time linking code. Only a "
                    "keyed hash of that code is stored until it is used or "
                    "expires; the iOS app does not retain the code.</p>"
                    "<p>If you choose another profile photo, Telescan accesses "
                    "only the image selected through the camera or system photo "
                    "picker. The app resizes and compresses it before uploading "
                    "a copy to Telescan cloud storage. You may also add an "
                    "optional BIO of up to 60 characters.</p>"
                    "<ul><li>Telegram ID, first name, and username</li>"
                    "<li>Random Telescan ID and active device sessions</li>"
                    "<li>Temporary keyed hashes of one-time linking codes</li>"
                    "<li>Telegram or user-selected profile photo</li>"
                    "<li>Optional BIO you add to your Telescan profile</li>"
                    "<li>Reports, blocks, and moderation records you create</li></ul>",
                ),
                (
                    "Nearby discovery",
                    "<p>While discoverability is enabled, the app broadcasts "
                    "your random Telescan ID over Bluetooth Low Energy. Nearby "
                    "Telescan devices use it to request the profile you share. "
                    "Signal strength and approximate distance are processed "
                    "locally and are not sent to the Telescan server. Blocked "
                    "Telescan IDs are cached locally so blocked profiles stay "
                    "hidden during network outages.</p>"
                    "<p>After a complete profile leaves the nearby list, the "
                    "app may keep its public profile snapshot and last-seen "
                    "time in a device-local Met history. The history contains "
                    "no GPS or distance measurements, is never uploaded, is "
                    "limited to 500 profiles, and is removed after 24 hours. "
                    "It can be cleared earlier and is also cleared on sign-out "
                    "or account deletion. Blocking removes the profile from "
                    "this local history.</p>",
                ),
                (
                    "Reports and blocks",
                    "<p>A report stores the reporter and target Telescan IDs, "
                    "reason, optional comment, a snapshot of the target name, "
                    "username, BIO and photo URL, review status, timestamps, and "
                    "moderator audit fields. The target is not shown the "
                    "reporter's identity.</p><p>A block stores the account "
                    "relationship, target profile snapshot, and creation time. "
                    "It hides profile access in both directions and can be "
                    "removed from the app.</p>",
                ),
                (
                    "Data we do not collect",
                    "<p>Telescan does not request or store GPS location or "
                    "server-side movement history, "
                    "contacts, Telegram messages, advertising identifiers, or "
                    "precise Bluetooth-distance history. It does not include "
                    "advertising or third-party analytics SDKs.</p>",
                ),
                (
                    "Use and sharing",
                    "<p>Account data is used only to register users, display "
                    "shared profiles, manage BIO and profile photos, operate nearby "
                    "discovery, process reports and blocks, prevent abuse, "
                    "and maintain the service. Telescan does not "
                    "sell personal data.</p>"
                    "<p>Data is disclosed to authenticated Telescan users who "
                    "receive or already know your public Telescan ID, to "
                    "infrastructure providers required to "
                    "operate the service, to authorized moderators reviewing "
                    "reports, or when required by law.</p>",
                ),
                (
                    "Security and retention",
                    "<p>API traffic uses encrypted HTTPS. One-time linking "
                    "codes are sent to the API over HTTPS and "
                    "retained only as keyed hashes "
                    "until use or expiry. Device sessions use short-lived "
                    "access tokens and rotating refresh tokens stored by the "
                    "iOS Keychain. During a limited backwards-compatibility "
                    "rollout, an additional SHA-256 code hash may be retained "
                    "for the older app and is removed after that rollout. "
                    "Account records, BIO and stored profile photos "
                    "remain until you delete the Telescan account. Blocks "
                    "remain until unblocked or account deletion. Pending "
                    "reports remain until a decision; resolved or dismissed "
                    "reports expire after 180 days.</p>"
                    "<p>Service infrastructure may process standard request "
                    "metadata such as IP address, time, host, "
                    "path, response status, and upstream timing for delivery, "
                    "reliability, and security — never for advertising or "
                    "behavioral analytics.</p>",
                ),
                (
                    "Account and data deletion",
                    "<p>Open your profile in the app, select <strong>Delete "
                    "account</strong>, and confirm. Telescan removes the live "
                    "account record, linking codes, device sessions, blocks, "
                    "stored photos, and local account data and caches. Report "
                    "relations are removed and retained snapshots follow the "
                    "limited moderation period. This operation "
                    "cannot be undone and does not affect your Telegram account.</p>",
                ),
                (
                    "Your choices",
                    "<p>You can disable discoverability, clear the device-local "
                    "24-hour encounter history, replace or remove your BIO and "
                    "profile photo, report or block profiles, manage blocked "
                    "profiles, sign out the current device, or delete "
                    "your account and all its sessions. Depending on applicable law, "
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
                    '<a href="mailto:admin@tgtelescan.ru">'
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
            effective_date="Действует с 24 августа 2026 года",
            sections=(
                (
                    "Общие положения",
                    "<p>Telescan — приложение для iOS, которое помогает "
                    "находить пользователей рядом и открывать публичные "
                    "профили Telegram, которыми они решили поделиться. "
                    "Политика распространяется на приложение, Telegram-бота, "
                    "API и поставщиков, обеспечивающих работу сервиса.</p>",
                ),
                (
                    "Какие данные мы обрабатываем",
                    "<p>При регистрации через Telegram-бота Telescan мы "
                    "получаем ваш Telegram ID, имя, username и текущую публичную "
                    "фотографию профиля. По вашему запросу API выпускает "
                    "одноразовый код привязки с коротким сроком действия. До "
                    "использования или истечения срока хранится только его "
                    "ключевой хеш; приложение iOS не сохраняет сам код.</p>"
                    "<p>Если вы выбираете другую фотографию, Telescan получает "
                    "доступ только к снимку, выбранному через камеру или "
                    "системный медиапикер. Приложение уменьшает и сжимает его "
                    "перед загрузкой копии в облачное хранилище. Вы также можете "
                    "добавить необязательное BIO длиной до 60 символов.</p>"
                    "<ul><li>Telegram ID, имя и username</li>"
                    "<li>Случайный Telescan ID и активные сессии устройств</li>"
                    "<li>Временные ключевые хеши одноразовых кодов привязки</li>"
                    "<li>Фотография из Telegram или выбранная вами</li>"
                    "<li>Необязательное BIO, добавленное вами в Telescan</li>"
                    "<li>Созданные вами жалобы, блокировки и записи модерации</li></ul>",
                ),
                (
                    "Поиск людей рядом",
                    "<p>Когда видимость включена, приложение передаёт ваш "
                    "случайный Telescan ID через Bluetooth Low Energy. Устройства Telescan "
                    "рядом используют его, чтобы запросить опубликованный вами "
                    "профиль. Сила сигнала и примерное расстояние обрабатываются "
                    "локально и не отправляются на сервер Telescan. Telescan ID "
                    "заблокированных профилей кешируются локально, чтобы они "
                    "не появлялись без сети.</p>"
                    "<p>После исчезновения полного профиля из списка рядом "
                    "приложение может сохранить его публичный снимок и время "
                    "последней встречи в локальном разделе «Виделись». История "
                    "не содержит GPS или замеров расстояния, не загружается на "
                    "сервер, ограничена 500 профилями и удаляется через 24 часа. "
                    "Её можно очистить раньше; она также очищается при выходе "
                    "или удалении аккаунта. Блокировка удаляет профиль из этой "
                    "локальной истории.</p>",
                ),
                (
                    "Жалобы и блокировки",
                    "<p>Жалоба содержит Telescan ID отправителя и цели, причину, "
                    "необязательный комментарий, снимок имени, username, BIO и URL "
                    "фотографии цели, статус, время и аудит модератора. Цель не "
                    "видит личность отправителя.</p><p>Блокировка содержит связь "
                    "аккаунтов, снимок профиля цели и время. Она скрывает "
                    "профили в обоих направлениях и может быть отменена в приложении.</p>",
                ),
                (
                    "Что мы не собираем",
                    "<p>Telescan не запрашивает и не хранит GPS-геолокацию, "
                    "серверную историю перемещений, контакты, сообщения Telegram, "
                    "рекламные идентификаторы или точную историю Bluetooth-"
                    "расстояний. В приложении нет рекламы и сторонних "
                    "аналитических SDK.</p>",
                ),
                (
                    "Использование и передача",
                    "<p>Данные аккаунта используются только для регистрации, "
                    "показа опубликованных профилей, управления BIO и фотографиями, "
                    "поиска людей рядом, обработки жалоб и блокировок, "
                    "предотвращения злоупотреблений и поддержки сервиса. Telescan не продаёт "
                    "персональные данные.</p>"
                    "<p>Данные раскрываются пользователям Telescan, которые "
                    "получили или уже знают ваш публичный Telescan ID, "
                    "поставщикам инфраструктуры для работы "
                    "сервиса, уполномоченным модераторам для рассмотрения жалоб "
                    "или когда этого требует закон.</p>",
                ),
                (
                    "Безопасность и хранение",
                    "<p>API работает через защищённое соединение HTTPS. "
                    "Одноразовые коды привязки передаются "
                    "API по HTTPS и до использования или истечения "
                    "срока хранятся только как ключевые хеши. Сессии устройств "
                    "используют короткоживущие access-токены и ротируемые "
                    "refresh-токены в iOS Keychain. На время ограниченного "
                    "переходного периода для старой версии приложения может "
                    "дополнительно храниться SHA-256-хеш кода; после перехода "
                    "он удаляется. Запись аккаунта, BIO и фотографии "
                    "хранятся до удаления аккаунта Telescan. Блокировки "
                    "хранятся до разблокировки или удаления аккаунта. Жалобы "
                    "до решения, а закрытые жалобы удаляются через 180 дней.</p>"
                    "<p>Инфраструктура сервиса может обрабатывать стандартные "
                    "данные запросов — IP-адрес, "
                    "время, host, путь, статус ответа и время upstream — для доставки, "
                    "надёжности и безопасности, но не для рекламы или "
                    "поведенческой аналитики.</p>",
                ),
                (
                    "Удаление аккаунта и данных",
                    "<p>Откройте профиль в приложении, выберите <strong>Удалить "
                    "аккаунт</strong> и подтвердите действие. Telescan удалит "
                    "активную запись аккаунта, коды привязки, сессии устройств, блокировки, "
                    "сохранённые фотографии, "
                    "локальные данные и кеши. Связь жалоб с удалённым аккаунтом "
                    "удаляется, а снимки профиля хранятся только в пределах "
                    "срока модерации. Операцию нельзя отменить; аккаунт "
                    "Telegram при этом не изменяется.</p>",
                ),
                (
                    "Ваш выбор",
                    "<p>Вы можете отключить видимость, очистить локальную "
                    "24-часовую историю встреч, заменить или удалить BIO и "
                    "фотографию, пожаловаться или заблокировать профиль, "
                    "управлять блокировками, выйти на текущем устройстве или удалить "
                    "аккаунт и все его сессии. "
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
                    '<a href="mailto:admin@tgtelescan.ru">'
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
            effective_date="Effective August 24, 2026",
            sections=(
                (
                    "Agreement",
                    "<p>These Terms govern your use of the Telescan iOS app, "
                    "Telegram bot, API, and related services. By continuing in "
                    "the app or using the service, you agree to these Terms and "
                    'the <a href="/privacy">Privacy Policy</a>. If you do not '
                    "agree, do not use Telescan.</p>",
                ),
                (
                    "The service",
                    "<p>Telescan helps nearby users discover and open public "
                    "Telegram profiles they choose to share. Bluetooth Low "
                    "Energy provides local discovery; an internet connection is "
                    "required for registration, profile loading, BIO and photo "
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
                    "your linked devices, Telegram account, profile "
                    "information, BIO, and uploaded photos. Share only content you "
                    "have the right to use.</p>"
                    "<p>Your Telescan ID is advertised nearby only while "
                    "discoverability is enabled. Authenticated users who already "
                    "know that identifier may still request the shared profile, "
                    "and radio identifiers can be observed or replayed by "
                    "devices in range.</p>"
                    "<p>You may report or block a profile. Blocking hides "
                    "profile access in both directions until you unblock it. "
                    "Reports must be submitted in good faith and contain only "
                    "relevant information.</p>",
                ),
                (
                    "Acceptable use",
                    "<p>Do not use Telescan to:</p><ul>"
                    "<li>Harass, stalk, threaten, impersonate, deceive, or harm</li>"
                    "<li>Collect, publish, or misuse another person’s data</li>"
                    "<li>Upload unlawful or rights-infringing content</li>"
                    "<li>Submit knowingly false or retaliatory reports</li>"
                    "<li>Probe, disrupt, overload, bypass, or interfere with the service</li>"
                    "<li>Use automation or reverse engineering unlawfully</li>"
                    "</ul><p>We may restrict access when reasonably necessary to "
                    "protect users, the service, or comply with law.</p>",
                ),
                (
                    "Third-party services",
                    "<p>Telescan relies on Telegram, Apple platforms, network "
                    "and hosting providers, storage providers, and other "
                    "infrastructure. "
                    "Their services and terms are "
                    "separate from ours. App Store distributions are also "
                    'subject to Apple’s <a href="https://www.apple.com/legal/'
                    'internet-services/itunes/dev/stdeula/" rel="noopener">'
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
                    '<p>Questions: <a href="mailto:admin@tgtelescan.ru">'
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
            effective_date="Действуют с 24 августа 2026 года",
            sections=(
                (
                    "Согласие с условиями",
                    "<p>Эти Условия регулируют использование приложения "
                    "Telescan для iOS, Telegram-бота, API и связанных сервисов. "
                    "Продолжая работу в приложении или используя сервис, вы "
                    'принимаете эти Условия и <a href="/privacy?lang=ru">'
                    "Политику конфиденциальности</a>. Если вы не согласны, не "
                    "используйте Telescan.</p>",
                ),
                (
                    "Сервис",
                    "<p>Telescan помогает пользователям рядом находить и "
                    "открывать публичные профили Telegram, которыми они решили "
                    "поделиться. Bluetooth Low Energy используется для поиска; "
                    "интернет требуется для регистрации, загрузки профилей, "
                    "управления BIO и фотографиями и удаления аккаунта.</p>"
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
                    "привязанные устройства, аккаунт Telegram, сведения профиля, BIO и "
                    "загруженные фотографии. Публикуйте только контент, на "
                    "использование которого у вас есть права.</p>"
                    "<p>Telescan ID передаётся устройствам рядом только при "
                    "включённой видимости. Пользователь, который уже знает этот "
                    "идентификатор, всё равно может запросить опубликованный "
                    "профиль, а радиоидентификаторы могут быть перехвачены или "
                    "повторены устройствами в зоне сигнала.</p>"
                    "<p>Вы можете пожаловаться на профиль или заблокировать его. "
                    "Блокировка скрывает профили в обоих направлениях до "
                    "разблокировки. Жалобы должны подаваться добросовестно и "
                    "содержать только относящуюся к нарушению информацию.</p>",
                ),
                (
                    "Допустимое использование",
                    "<p>Запрещено использовать Telescan, чтобы:</p><ul>"
                    "<li>Преследовать, запугивать, выдавать себя за другого или причинять вред</li>"
                    "<li>Собирать, публиковать или неправомерно использовать чужие данные</li>"
                    "<li>Загружать незаконный контент или нарушать чужие права</li>"
                    "<li>Отправлять заведомо ложные жалобы или использовать их для мести</li>"
                    "<li>Исследовать, нарушать, перегружать или обходить защиту сервиса</li>"
                    "<li>Незаконно применять автоматизацию или обратную разработку</li>"
                    "</ul><p>Мы можем ограничить доступ, когда это обоснованно "
                    "необходимо для защиты пользователей, сервиса или соблюдения закона.</p>",
                ),
                (
                    "Сторонние сервисы",
                    "<p>Telescan зависит от Telegram, платформ Apple, "
                    "поставщиков сетевой и серверной инфраструктуры, "
                    "хранилищ и других сервисов. Их "
                    "сервисы и условия не "
                    "являются частью наших. Приложение из App Store также "
                    'подчиняется <a href="https://www.apple.com/legal/internet-'
                    'services/itunes/dev/stdeula/" rel="noopener">стандартному '
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
                    '<a href="mailto:admin@tgtelescan.ru">'
                    "admin@tgtelescan.ru</a>.</p>",
                ),
            ),
        ),
    },
}


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


@lru_cache(maxsize=1)
def _page_template() -> Template:
    path = Path(__file__).resolve().parents[1] / "templates" / "legal.html"
    return Template(path.read_text(encoding="utf-8"))


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
        f"<section><h2>{escape(title)}</h2>{body}</section>"
        for title, body in document.sections
    )

    return _page_template().substitute(
        current_label=current_label,
        effective_date=escape(document.effective_date),
        kind=kind,
        language=language,
        language_name=language_name,
        opposite_language=opposite_language,
        other_kind=other_kind,
        other_label=other_label,
        other_title=escape(other_document.title),
        sections=sections,
        summary=escape(document.summary),
        title=escape(document.title),
    )
