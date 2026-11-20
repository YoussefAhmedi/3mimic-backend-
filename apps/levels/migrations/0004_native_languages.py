"""
Adds ~100 more languages so users can pick their NATIVE language from a full list (with search in the app).

* They are created with is_active=False: that flag means "can be *learned*", so they appear only in the
  native-language picker, never in "What language do you want to learn?".
* Existing languages (en, es, fr, de, ar) are left exactly as they are.
* Codes are the ones the translators use (deep-translator / Google): Hebrew is "iw", Chinese is
  "zh-CN" / "zh-TW", Filipino is "tl", Javanese is "jw".

Turn one on for learning later from Django admin (Languages -> "Is active") once it has video content.
"""
from django.db import migrations

# (code, English name, name in its own language, flag, right-to-left)
LANGUAGES = [
    ("af", "Afrikaans", "Afrikaans", "🇿🇦", False),
    ("am", "Amharic", "አማርኛ", "🇪🇹", False),
    ("as", "Assamese", "অসমীয়া", "🇮🇳", False),
    ("az", "Azerbaijani", "Azərbaycanca", "🇦🇿", False),
    ("be", "Belarusian", "Беларуская", "🇧🇾", False),
    ("bg", "Bulgarian", "Български", "🇧🇬", False),
    ("bn", "Bengali", "বাংলা", "🇧🇩", False),
    ("bs", "Bosnian", "Bosanski", "🇧🇦", False),
    ("ca", "Catalan", "Català", "🇪🇸", False),
    ("ceb", "Cebuano", "Cebuano", "🇵🇭", False),
    ("ckb", "Kurdish (Sorani)", "کوردی", "🇮🇶", True),
    ("cs", "Czech", "Čeština", "🇨🇿", False),
    ("cy", "Welsh", "Cymraeg", "🇬🇧", False),
    ("da", "Danish", "Dansk", "🇩🇰", False),
    ("dv", "Dhivehi", "ދިވެހި", "🇲🇻", True),
    ("el", "Greek", "Ελληνικά", "🇬🇷", False),
    ("eo", "Esperanto", "Esperanto", "🌐", False),
    ("et", "Estonian", "Eesti", "🇪🇪", False),
    ("eu", "Basque", "Euskara", "🇪🇸", False),
    ("fa", "Persian", "فارسی", "🇮🇷", True),
    ("fi", "Finnish", "Suomi", "🇫🇮", False),
    ("fy", "Frisian", "Frysk", "🇳🇱", False),
    ("ga", "Irish", "Gaeilge", "🇮🇪", False),
    ("gd", "Scottish Gaelic", "Gàidhlig", "🇬🇧", False),
    ("gl", "Galician", "Galego", "🇪🇸", False),
    ("gn", "Guarani", "Avañe'ẽ", "🇵🇾", False),
    ("gu", "Gujarati", "ગુજરાતી", "🇮🇳", False),
    ("ha", "Hausa", "Hausa", "🇳🇬", False),
    ("haw", "Hawaiian", "ʻŌlelo Hawaiʻi", "🇺🇸", False),
    ("hi", "Hindi", "हिन्दी", "🇮🇳", False),
    ("hr", "Croatian", "Hrvatski", "🇭🇷", False),
    ("ht", "Haitian Creole", "Kreyòl ayisyen", "🇭🇹", False),
    ("hu", "Hungarian", "Magyar", "🇭🇺", False),
    ("hy", "Armenian", "Հայերեն", "🇦🇲", False),
    ("id", "Indonesian", "Bahasa Indonesia", "🇮🇩", False),
    ("ig", "Igbo", "Igbo", "🇳🇬", False),
    ("is", "Icelandic", "Íslenska", "🇮🇸", False),
    ("it", "Italian", "Italiano", "🇮🇹", False),
    ("iw", "Hebrew", "עברית", "🇮🇱", True),
    ("ja", "Japanese", "日本語", "🇯🇵", False),
    ("jw", "Javanese", "Basa Jawa", "🇮🇩", False),
    ("ka", "Georgian", "ქართული", "🇬🇪", False),
    ("kk", "Kazakh", "Қазақша", "🇰🇿", False),
    ("km", "Khmer", "ខ្មែរ", "🇰🇭", False),
    ("kn", "Kannada", "ಕನ್ನಡ", "🇮🇳", False),
    ("ko", "Korean", "한국어", "🇰🇷", False),
    ("ku", "Kurdish (Kurmanji)", "Kurdî", "🇮🇶", False),
    ("ky", "Kyrgyz", "Кыргызча", "🇰🇬", False),
    ("la", "Latin", "Latina", "🇻🇦", False),
    ("lb", "Luxembourgish", "Lëtzebuergesch", "🇱🇺", False),
    ("lg", "Luganda", "Luganda", "🇺🇬", False),
    ("ln", "Lingala", "Lingála", "🇨🇩", False),
    ("lo", "Lao", "ລາວ", "🇱🇦", False),
    ("lt", "Lithuanian", "Lietuvių", "🇱🇹", False),
    ("lv", "Latvian", "Latviešu", "🇱🇻", False),
    ("mg", "Malagasy", "Malagasy", "🇲🇬", False),
    ("mi", "Maori", "Te Reo Māori", "🇳🇿", False),
    ("mk", "Macedonian", "Македонски", "🇲🇰", False),
    ("ml", "Malayalam", "മലയാളം", "🇮🇳", False),
    ("mn", "Mongolian", "Монгол", "🇲🇳", False),
    ("mr", "Marathi", "मराठी", "🇮🇳", False),
    ("ms", "Malay", "Bahasa Melayu", "🇲🇾", False),
    ("mt", "Maltese", "Malti", "🇲🇹", False),
    ("my", "Burmese", "မြန်မာ", "🇲🇲", False),
    ("ne", "Nepali", "नेपाली", "🇳🇵", False),
    ("nl", "Dutch", "Nederlands", "🇳🇱", False),
    ("no", "Norwegian", "Norsk", "🇳🇴", False),
    ("ny", "Chichewa", "Chichewa", "🇲🇼", False),
    ("om", "Oromo", "Afaan Oromoo", "🇪🇹", False),
    ("or", "Odia", "ଓଡ଼ିଆ", "🇮🇳", False),
    ("pa", "Punjabi", "ਪੰਜਾਬੀ", "🇮🇳", False),
    ("pl", "Polish", "Polski", "🇵🇱", False),
    ("ps", "Pashto", "پښتو", "🇦🇫", True),
    ("pt", "Portuguese", "Português", "🇵🇹", False),
    ("qu", "Quechua", "Runasimi", "🇵🇪", False),
    ("ro", "Romanian", "Română", "🇷🇴", False),
    ("ru", "Russian", "Русский", "🇷🇺", False),
    ("rw", "Kinyarwanda", "Kinyarwanda", "🇷🇼", False),
    ("sa", "Sanskrit", "संस्कृतम्", "🇮🇳", False),
    ("sd", "Sindhi", "سنڌي", "🇵🇰", True),
    ("si", "Sinhala", "සිංහල", "🇱🇰", False),
    ("sk", "Slovak", "Slovenčina", "🇸🇰", False),
    ("sl", "Slovenian", "Slovenščina", "🇸🇮", False),
    ("sm", "Samoan", "Gagana Sāmoa", "🇼🇸", False),
    ("sn", "Shona", "ChiShona", "🇿🇼", False),
    ("so", "Somali", "Soomaali", "🇸🇴", False),
    ("sq", "Albanian", "Shqip", "🇦🇱", False),
    ("sr", "Serbian", "Српски", "🇷🇸", False),
    ("st", "Sesotho", "Sesotho", "🇱🇸", False),
    ("su", "Sundanese", "Basa Sunda", "🇮🇩", False),
    ("sv", "Swedish", "Svenska", "🇸🇪", False),
    ("sw", "Swahili", "Kiswahili", "🇹🇿", False),
    ("ta", "Tamil", "தமிழ்", "🇮🇳", False),
    ("te", "Telugu", "తెలుగు", "🇮🇳", False),
    ("tg", "Tajik", "Тоҷикӣ", "🇹🇯", False),
    ("th", "Thai", "ไทย", "🇹🇭", False),
    ("ti", "Tigrinya", "ትግርኛ", "🇪🇷", False),
    ("tk", "Turkmen", "Türkmençe", "🇹🇲", False),
    ("tl", "Filipino", "Filipino", "🇵🇭", False),
    ("tr", "Turkish", "Türkçe", "🇹🇷", False),
    ("tt", "Tatar", "Татарча", "🇷🇺", False),
    ("ug", "Uyghur", "ئۇيغۇرچە", "🇨🇳", True),
    ("uk", "Ukrainian", "Українська", "🇺🇦", False),
    ("ur", "Urdu", "اردو", "🇵🇰", True),
    ("uz", "Uzbek", "Oʻzbekcha", "🇺🇿", False),
    ("vi", "Vietnamese", "Tiếng Việt", "🇻🇳", False),
    ("xh", "Xhosa", "isiXhosa", "🇿🇦", False),
    ("yi", "Yiddish", "ייִדיש", "🇮🇱", True),
    ("yo", "Yoruba", "Yorùbá", "🇳🇬", False),
    ("zh-CN", "Chinese (Simplified)", "简体中文", "🇨🇳", False),
    ("zh-TW", "Chinese (Traditional)", "繁體中文", "🇹🇼", False),
    ("zu", "Zulu", "isiZulu", "🇿🇦", False),
]


def add_languages(apps, schema_editor):
    Language = apps.get_model("levels", "Language")
    for code, name, native_name, flag, rtl in LANGUAGES:
        # get_or_create: a language that already exists is never modified.
        Language.objects.get_or_create(
            code=code,
            defaults={"name": name, "native_name": native_name, "flag": flag, "is_rtl": rtl, "is_active": False},
        )


class Migration(migrations.Migration):
    dependencies = [("levels", "0003_levels_v2")]
    operations = [migrations.RunPython(add_languages, migrations.RunPython.noop)]
