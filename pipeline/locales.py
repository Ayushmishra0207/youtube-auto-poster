"""
Locale/region targeting — country/continent selection drives language,
TTS voice, on-screen font+script handling, news/trends sources, YouTube
upload metadata language, and base SEO tags/hashtags.

Every tts_voice/gtts_lang value here was verified against the real
edge-tts voice list and gtts.lang.tts_langs() (2026-07-19), not guessed.

Script families:
  latin       — shared Noto Sans Latin/Cyrillic/Greek font, word-wrap, LTR
  devanagari  — Noto Sans Devanagari, word-wrap, LTR, needs _fix_devanagari
  bengali     — Noto Sans Bengali, word-wrap, LTR
  arabic      — Noto Sans Arabic, word-wrap (RTL — needs bidi/reshaping)
  hebrew      — Noto Sans Hebrew, word-wrap (RTL — needs bidi/reshaping)
  cjk         — Noto Sans SC/JP/KR, CHARACTER-wrap (no spaces), LTR
  thai        — Noto Sans Thai, CHARACTER-wrap (no spaces), LTR
"""
from dataclasses import dataclass

from config import ASSETS_DIR, TTS_VOICE

FONTS_DIR = ASSETS_DIR / "fonts"


@dataclass
class ScriptProfile:
    """Rendering/font behavior shared by every locale using this script."""
    font_family: str          # Noto Sans variant name, used for font filenames
    rtl: bool = False
    wrap_mode: str = "word"   # "word" or "char" (CJK/Thai have no spaces)


SCRIPT_PROFILES: dict[str, ScriptProfile] = {
    "latin":      ScriptProfile(font_family="NotoSans"),
    "devanagari": ScriptProfile(font_family="NotoSansDevanagari"),
    "bengali":    ScriptProfile(font_family="NotoSansBengali"),
    "arabic":     ScriptProfile(font_family="NotoSansArabic", rtl=True),
    "hebrew":     ScriptProfile(font_family="NotoSansHebrew", rtl=True),
    "cjk_sc":     ScriptProfile(font_family="NotoSansSC", wrap_mode="char"),
    "cjk_jp":     ScriptProfile(font_family="NotoSansJP", wrap_mode="char"),
    "cjk_kr":     ScriptProfile(font_family="NotoSansKR", wrap_mode="char"),
    "thai":       ScriptProfile(font_family="NotoSansThai", wrap_mode="char"),
}


@dataclass
class Locale:
    code: str            # internal locale key, e.g. "hi", "es", "ar"
    label: str            # human label for the UI, e.g. "Hindi (India)"
    continent: str
    language_name: str    # for LLM prompts, e.g. "Hindi", "Spanish"
    script: str           # key into SCRIPT_PROFILES
    tts_voice: str         # verified real edge-tts ShortName
    gtts_lang: str | None  # verified real gtts.lang code, or None if unsupported
    news_hl: str
    news_gl: str
    news_ceid: str
    trends_pn: str         # pytrends country param
    yt_language: str       # YouTube defaultLanguage / defaultAudioLanguage
    base_tags: list[str]
    default_hashtags: list[str]
    subscribe_cta: str      # outro card line 1
    like_share_cta: str     # outro card line 2
    breaking_badge: str      # thumbnail "BREAKING" style badge text

    @property
    def script_profile(self) -> ScriptProfile:
        return SCRIPT_PROFILES[self.script]

    @property
    def font_bold(self) -> str:
        return str(FONTS_DIR / f"{self.script_profile.font_family}-Bold.ttf")

    @property
    def font_regular(self) -> str:
        return str(FONTS_DIR / f"{self.script_profile.font_family}-Regular.ttf")


LOCALES: dict[str, Locale] = {
    "hi": Locale(
        code="hi", label="India (Hindi)", continent="Asia", language_name="Hindi",
        script="devanagari", tts_voice=TTS_VOICE, gtts_lang="hi",
        news_hl="hi-IN", news_gl="IN", news_ceid="IN:hi", trends_pn="india",
        yt_language="hi",
        base_tags=["hindi news", "trending news india"],
        default_hashtags=["#Hindi", "#News", "#Trending", "#India"],
        subscribe_cta="चैनल को Subscribe करें",
        like_share_cta="Like, Share और घंटी दबाना न भूलें!",
        breaking_badge="बड़ी खबर",
    ),
    "en-US": Locale(
        code="en-US", label="USA (English)", continent="Americas", language_name="English",
        script="latin", tts_voice="en-US-AndrewNeural", gtts_lang="en",
        news_hl="en-US", news_gl="US", news_ceid="US:en", trends_pn="united_states",
        yt_language="en",
        base_tags=["us news", "trending news usa"],
        default_hashtags=["#News", "#Trending", "#USA"],
        subscribe_cta="Subscribe to the channel",
        like_share_cta="Like, share, and hit the bell!",
        breaking_badge="BREAKING",
    ),
    "en-GB": Locale(
        code="en-GB", label="UK (English)", continent="Europe", language_name="English",
        script="latin", tts_voice="en-GB-RyanNeural", gtts_lang="en",
        news_hl="en-GB", news_gl="GB", news_ceid="GB:en", trends_pn="united_kingdom",
        yt_language="en",
        base_tags=["uk news", "trending news uk"],
        default_hashtags=["#News", "#Trending", "#UK"],
        subscribe_cta="Subscribe to the channel",
        like_share_cta="Like, share, and hit the bell!",
        breaking_badge="BREAKING",
    ),
    "es": Locale(
        code="es", label="Spain (Spanish)", continent="Europe", language_name="Spanish",
        script="latin", tts_voice="es-ES-AlvaroNeural", gtts_lang="es",
        news_hl="es-ES", news_gl="ES", news_ceid="ES:es", trends_pn="spain",
        yt_language="es",
        base_tags=["noticias españa", "noticias de tendencia"],
        default_hashtags=["#Noticias", "#Tendencia", "#España"],
        subscribe_cta="Suscríbete al canal",
        like_share_cta="¡Dale like, comparte y activa la campanita!",
        breaking_badge="ÚLTIMA HORA",
    ),
    "es-MX": Locale(
        code="es-MX", label="Mexico / Latin America (Spanish)", continent="Americas", language_name="Spanish",
        script="latin", tts_voice="es-MX-JorgeNeural", gtts_lang="es",
        news_hl="es-419", news_gl="MX", news_ceid="MX:es-419", trends_pn="mexico",
        yt_language="es",
        base_tags=["noticias méxico", "noticias de tendencia"],
        default_hashtags=["#Noticias", "#Tendencia", "#México"],
        subscribe_cta="Suscríbete al canal",
        like_share_cta="¡Dale like, comparte y activa la campanita!",
        breaking_badge="ÚLTIMA HORA",
    ),
    "pt-BR": Locale(
        code="pt-BR", label="Brazil (Portuguese)", continent="Americas", language_name="Portuguese",
        script="latin", tts_voice="pt-BR-AntonioNeural", gtts_lang="pt",
        news_hl="pt-BR", news_gl="BR", news_ceid="BR:pt-419", trends_pn="brazil",
        yt_language="pt",
        base_tags=["notícias brasil", "notícias em alta"],
        default_hashtags=["#Notícias", "#EmAlta", "#Brasil"],
        subscribe_cta="Inscreva-se no canal",
        like_share_cta="Curta, compartilhe e ative o sininho!",
        breaking_badge="URGENTE",
    ),
    "fr": Locale(
        code="fr", label="France (French)", continent="Europe", language_name="French",
        script="latin", tts_voice="fr-FR-HenriNeural", gtts_lang="fr",
        news_hl="fr", news_gl="FR", news_ceid="FR:fr", trends_pn="france",
        yt_language="fr",
        base_tags=["actualités france", "actualités tendance"],
        default_hashtags=["#Actualités", "#Tendance", "#France"],
        subscribe_cta="Abonnez-vous à la chaîne",
        like_share_cta="Aimez, partagez et activez la cloche !",
        breaking_badge="DERNIÈRE MINUTE",
    ),
    "de": Locale(
        code="de", label="Germany (German)", continent="Europe", language_name="German",
        script="latin", tts_voice="de-DE-ConradNeural", gtts_lang="de",
        news_hl="de", news_gl="DE", news_ceid="DE:de", trends_pn="germany",
        yt_language="de",
        base_tags=["nachrichten deutschland", "trending news deutschland"],
        default_hashtags=["#Nachrichten", "#Trending", "#Deutschland"],
        subscribe_cta="Abonniere den Kanal",
        like_share_cta="Like, teile und aktiviere die Glocke!",
        breaking_badge="EILMELDUNG",
    ),
    "it": Locale(
        code="it", label="Italy (Italian)", continent="Europe", language_name="Italian",
        script="latin", tts_voice="it-IT-DiegoNeural", gtts_lang="it",
        news_hl="it", news_gl="IT", news_ceid="IT:it", trends_pn="italy",
        yt_language="it",
        base_tags=["notizie italia", "notizie di tendenza"],
        default_hashtags=["#Notizie", "#Tendenza", "#Italia"],
        subscribe_cta="Iscriviti al canale",
        like_share_cta="Metti like, condividi e attiva la campanella!",
        breaking_badge="ULTIM'ORA",
    ),
    "nl": Locale(
        code="nl", label="Netherlands (Dutch)", continent="Europe", language_name="Dutch",
        script="latin", tts_voice="nl-NL-MaartenNeural", gtts_lang="nl",
        news_hl="nl", news_gl="NL", news_ceid="NL:nl", trends_pn="netherlands",
        yt_language="nl",
        base_tags=["nieuws nederland", "trending nieuws"],
        default_hashtags=["#Nieuws", "#Trending", "#Nederland"],
        subscribe_cta="Abonneer je op het kanaal",
        like_share_cta="Like, deel en zet de bel aan!",
        breaking_badge="BREAKING NEWS",
    ),
    "pl": Locale(
        code="pl", label="Poland (Polish)", continent="Europe", language_name="Polish",
        script="latin", tts_voice="pl-PL-MarekNeural", gtts_lang="pl",
        news_hl="pl", news_gl="PL", news_ceid="PL:pl", trends_pn="poland",
        yt_language="pl",
        base_tags=["wiadomości polska", "popularne wiadomości"],
        default_hashtags=["#Wiadomości", "#naCzasie", "#Polska"],
        subscribe_cta="Subskrybuj kanał",
        like_share_cta="Polub, udostępnij i włącz dzwoneczek!",
        breaking_badge="PILNE",
    ),
    "tr": Locale(
        code="tr", label="Turkey (Turkish)", continent="Asia", language_name="Turkish",
        script="latin", tts_voice="tr-TR-AhmetNeural", gtts_lang="tr",
        news_hl="tr", news_gl="TR", news_ceid="TR:tr", trends_pn="turkey",
        yt_language="tr",
        base_tags=["türkiye haberleri", "gündem haberler"],
        default_hashtags=["#Haber", "#Gündem", "#Türkiye"],
        subscribe_cta="Kanala abone ol",
        like_share_cta="Beğen, paylaş ve zil simgesine tıkla!",
        breaking_badge="SON DAKİKA",
    ),
    "vi": Locale(
        code="vi", label="Vietnam (Vietnamese)", continent="Asia", language_name="Vietnamese",
        script="latin", tts_voice="vi-VN-NamMinhNeural", gtts_lang="vi",
        news_hl="vi", news_gl="VN", news_ceid="VN:vi", trends_pn="vietnam",
        yt_language="vi",
        base_tags=["tin tức việt nam", "tin xu hướng"],
        default_hashtags=["#TinTức", "#XuHướng", "#VietNam"],
        subscribe_cta="Đăng ký kênh",
        like_share_cta="Thích, chia sẻ và bấm chuông!",
        breaking_badge="TIN NÓNG",
    ),
    "id": Locale(
        code="id", label="Indonesia (Indonesian)", continent="Asia", language_name="Indonesian",
        script="latin", tts_voice="id-ID-ArdiNeural", gtts_lang="id",
        news_hl="id", news_gl="ID", news_ceid="ID:id", trends_pn="indonesia",
        yt_language="id",
        base_tags=["berita indonesia", "berita trending"],
        default_hashtags=["#Berita", "#Trending", "#Indonesia"],
        subscribe_cta="Berlangganan channel ini",
        like_share_cta="Like, bagikan, dan aktifkan lonceng!",
        breaking_badge="BERITA TERBARU",
    ),
    "fil": Locale(
        code="fil", label="Philippines (Filipino)", continent="Asia", language_name="Filipino",
        script="latin", tts_voice="fil-PH-AngeloNeural", gtts_lang="tl",
        news_hl="fil", news_gl="PH", news_ceid="PH:fil", trends_pn="philippines",
        yt_language="fil",
        base_tags=["balita pilipinas", "trending balita"],
        default_hashtags=["#Balita", "#Trending", "#Pilipinas"],
        subscribe_cta="Mag-subscribe sa channel",
        like_share_cta="I-like, i-share, at i-click ang bell!",
        breaking_badge="BREAKING NEWS",
    ),
    "sw": Locale(
        code="sw", label="Kenya / East Africa (Swahili)", continent="Africa", language_name="Swahili",
        script="latin", tts_voice="sw-KE-RafikiNeural", gtts_lang="sw",
        news_hl="sw", news_gl="KE", news_ceid="KE:sw", trends_pn="kenya",
        yt_language="sw",
        base_tags=["habari kenya", "habari za mtindo"],
        default_hashtags=["#Habari", "#Trending", "#Kenya"],
        subscribe_cta="Jiunge na channel",
        like_share_cta="Penda, shiriki, na bonyeza kengele!",
        breaking_badge="HABARI MPYA",
    ),
    "ru": Locale(
        code="ru", label="Russia (Russian)", continent="Europe", language_name="Russian",
        script="latin", tts_voice="ru-RU-DmitryNeural", gtts_lang="ru",
        news_hl="ru", news_gl="RU", news_ceid="RU:ru", trends_pn="russia",
        yt_language="ru",
        base_tags=["новости россии", "трендовые новости"],
        default_hashtags=["#Новости", "#Тренды", "#Россия"],
        subscribe_cta="Подпишись на канал",
        like_share_cta="Ставь лайк, делись и жми на колокольчик!",
        breaking_badge="СРОЧНЫЕ НОВОСТИ",
    ),
    "el": Locale(
        code="el", label="Greece (Greek)", continent="Europe", language_name="Greek",
        script="latin", tts_voice="el-GR-NestorasNeural", gtts_lang="el",
        news_hl="el", news_gl="GR", news_ceid="GR:el", trends_pn="greece",
        yt_language="el",
        base_tags=["ειδήσεις ελλάδα", "τάσεις ειδήσεις"],
        default_hashtags=["#Ειδήσεις", "#Τάσεις", "#Ελλάδα"],
        subscribe_cta="Εγγραφείτε στο κανάλι",
        like_share_cta="Κάντε like, κοινοποιήστε και πατήστε το καμπανάκι!",
        breaking_badge="ΕΚΤΑΚΤΟ",
    ),
    "bn": Locale(
        code="bn", label="Bangladesh (Bengali)", continent="Asia", language_name="Bengali",
        script="bengali", tts_voice="bn-BD-PradeepNeural", gtts_lang="bn",
        news_hl="bn", news_gl="BD", news_ceid="BD:bn", trends_pn="bangladesh",
        yt_language="bn",
        base_tags=["বাংলাদেশ সংবাদ", "ট্রেন্ডিং নিউজ"],
        default_hashtags=["#সংবাদ", "#ট্রেন্ডিং", "#বাংলাদেশ"],
        subscribe_cta="চ্যানেল সাবস্ক্রাইব করুন",
        like_share_cta="লাইক, শেয়ার করুন এবং বেল আইকনে ক্লিক করুন!",
        breaking_badge="জরুরি খবর",
    ),
    "ur": Locale(
        code="ur", label="Pakistan (Urdu)", continent="Asia", language_name="Urdu",
        script="arabic", tts_voice="ur-PK-AsadNeural", gtts_lang="ur",
        news_hl="ur", news_gl="PK", news_ceid="PK:ur", trends_pn="pakistan",
        yt_language="ur",
        base_tags=["پاکستان خبریں", "ٹرینڈنگ خبریں"],
        default_hashtags=["#خبریں", "#ٹرینڈنگ", "#پاکستان"],
        subscribe_cta="چینل کو سبسکرائب کریں",
        like_share_cta="لائیک، شیئر کریں اور بیل آئیکن دبائیں!",
        breaking_badge="بریکنگ نیوز",
    ),
    "ar": Locale(
        code="ar", label="Saudi Arabia / Middle East (Arabic)", continent="Asia", language_name="Arabic",
        script="arabic", tts_voice="ar-SA-HamedNeural", gtts_lang="ar",
        news_hl="ar", news_gl="SA", news_ceid="SA:ar", trends_pn="saudi_arabia",
        yt_language="ar",
        base_tags=["أخبار السعودية", "أخبار رائجة"],
        default_hashtags=["#أخبار", "#رائج", "#السعودية"],
        subscribe_cta="اشترك في القناة",
        like_share_cta="أعجبك الفيديو؟ شارك واضغط الجرس!",
        breaking_badge="عاجل",
    ),
    "fa": Locale(
        code="fa", label="Iran (Persian)", continent="Asia", language_name="Persian",
        script="arabic", tts_voice="fa-IR-FaridNeural", gtts_lang=None,
        news_hl="fa", news_gl="IR", news_ceid="IR:fa", trends_pn="iran",
        yt_language="fa",
        base_tags=["اخبار ایران", "اخبار داغ"],
        default_hashtags=["#اخبار", "#داغ", "#ایران"],
        subscribe_cta="در کانال عضو شوید",
        like_share_cta="لایک کنید، به اشتراک بگذارید و زنگ را بزنید!",
        breaking_badge="فوری",
    ),
    "he": Locale(
        code="he", label="Israel (Hebrew)", continent="Asia", language_name="Hebrew",
        script="hebrew", tts_voice="he-IL-AvriNeural", gtts_lang="iw",
        news_hl="he", news_gl="IL", news_ceid="IL:he", trends_pn="israel",
        yt_language="he",
        base_tags=["חדשות ישראל", "חדשות חמות"],
        default_hashtags=["#חדשות", "#חם", "#ישראל"],
        subscribe_cta="הירשמו לערוץ",
        like_share_cta="לייק, שתפו ולחצו על הפעמון!",
        breaking_badge="מבזק",
    ),
    "zh": Locale(
        code="zh", label="China (Chinese, Simplified)", continent="Asia", language_name="Chinese",
        script="cjk_sc", tts_voice="zh-CN-YunxiNeural", gtts_lang="zh-CN",
        news_hl="zh-CN", news_gl="CN", news_ceid="CN:zh-Hans", trends_pn="china",
        yt_language="zh-Hans",
        base_tags=["中国新闻", "热门新闻"],
        default_hashtags=["#新闻", "#热门", "#中国"],
        subscribe_cta="订阅频道",
        like_share_cta="点赞、分享并点击铃铛！",
        breaking_badge="突发新闻",
    ),
    "ja": Locale(
        code="ja", label="Japan (Japanese)", continent="Asia", language_name="Japanese",
        script="cjk_jp", tts_voice="ja-JP-KeitaNeural", gtts_lang="ja",
        news_hl="ja", news_gl="JP", news_ceid="JP:ja", trends_pn="japan",
        yt_language="ja",
        base_tags=["日本のニュース", "トレンドニュース"],
        default_hashtags=["#ニュース", "#トレンド", "#日本"],
        subscribe_cta="チャンネル登録をお願いします",
        like_share_cta="いいね・シェアして、ベルを押してね！",
        breaking_badge="速報",
    ),
    "ko": Locale(
        code="ko", label="South Korea (Korean)", continent="Asia", language_name="Korean",
        script="cjk_kr", tts_voice="ko-KR-InJoonNeural", gtts_lang="ko",
        news_hl="ko", news_gl="KR", news_ceid="KR:ko", trends_pn="south_korea",
        yt_language="ko",
        base_tags=["한국 뉴스", "인기 뉴스"],
        default_hashtags=["#뉴스", "#인기", "#한국"],
        subscribe_cta="채널을 구독해 주세요",
        like_share_cta="좋아요, 공유하고 알림 설정하세요!",
        breaking_badge="속보",
    ),
    "th": Locale(
        code="th", label="Thailand (Thai)", continent="Asia", language_name="Thai",
        script="thai", tts_voice="th-TH-NiwatNeural", gtts_lang="th",
        news_hl="th", news_gl="TH", news_ceid="TH:th", trends_pn="thailand",
        yt_language="th",
        base_tags=["ข่าวไทย", "ข่าวกำลังฮิต"],
        default_hashtags=["#ข่าว", "#กำลังฮิต", "#ไทย"],
        subscribe_cta="สมัครสมาชิกช่องนี้",
        like_share_cta="กดไลก์ แชร์ และกดกระดิ่งแจ้งเตือน!",
        breaking_badge="ข่าวด่วน",
    ),
    "au": Locale(
        code="au", label="Australia (English)", continent="Oceania", language_name="English",
        script="latin", tts_voice="en-US-AndrewNeural", gtts_lang="en",
        news_hl="en-AU", news_gl="AU", news_ceid="AU:en", trends_pn="australia",
        yt_language="en",
        base_tags=["australia news", "trending news australia"],
        default_hashtags=["#News", "#Trending", "#Australia"],
        subscribe_cta="Subscribe to the channel",
        like_share_cta="Like, share, and hit the bell!",
        breaking_badge="BREAKING",
    ),
}

DEFAULT_LOCALE = "hi"


def get_locale(code: str | None) -> Locale:
    """Return the Locale for a code, falling back to the default (Hindi/India)."""
    if not code:
        return LOCALES[DEFAULT_LOCALE]
    return LOCALES.get(code, LOCALES[DEFAULT_LOCALE])


# Category → thumbnail-badge text override. Hindi-only for now since every
# configured slot in topic_config.json uses the Hindi locale in practice —
# any category not listed here (including all actual news categories) keeps
# the locale's default `breaking_badge` ("बड़ी खबर" style), which is correct
# for real news content. Falls back to breaking_badge for every other locale
# too, since we have no translated labels for those yet.
_CATEGORY_BADGE_HI: dict[str, str] = {
    "famous_story":     "कहानी",
    "historical_story": "कहानी",
    "science_tech":      "जानिए",
    "sports":            "स्पोर्ट्स अपडेट",
    "entertainment":     "एंटरटेनमेंट",
    "custom_topic":      "जानिए",
    "movie_explained":   "मूवी रिव्यू",
}


def category_badge_text(category: str, locale: Locale) -> str:
    """
    Thumbnail badge text for a given topic category, in the given locale.
    Prevents stamping "breaking news" on non-news content (stories, science,
    sports, entertainment), which was previously unconditional and misled
    viewers about what the video actually delivers.
    """
    if locale.code == "hi" and category in _CATEGORY_BADGE_HI:
        return _CATEGORY_BADGE_HI[category]
    return locale.breaking_badge


def locales_by_continent() -> dict[str, list[Locale]]:
    """Group locales by continent, for a UI picker."""
    grouped: dict[str, list[Locale]] = {}
    for loc in LOCALES.values():
        grouped.setdefault(loc.continent, []).append(loc)
    for group in grouped.values():
        group.sort(key=lambda l: l.label)
    return grouped
