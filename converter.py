"""Markdown to Unicode converter.

Converts Markdown formatting (bold, italic, bold+italic, monospace)
into Unicode mathematical alphanumeric characters so that text renders
correctly on platforms that don't support Markdown (e.g. LinkedIn posts).

Based on https://github.com/USBashka/markdown2unicode (GPL v3).
"""


class Mode:
    REGULAR = 0
    BOLD = 1
    ITALIC = 2
    BOLDITALIC = 3
    MONO = 4


class Remaps:
    regular = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()_-+=?/|'\"`"
    bold = "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗!@#$%^&*()_-+=?/|'\"`"
    italic = "𝘈𝘉𝘊𝘋𝘌𝘍𝘎𝘏𝘐𝘑𝘒𝘓𝘔𝘕𝘖𝘗𝘘𝘙𝘚𝘛𝘜𝘝𝘞𝘟𝘠𝘡𝘢𝘣𝘤𝘥𝘦𝘧𝘨𝘩𝘪𝘫𝘬𝘭𝘮𝘯𝘰𝘱𝘲𝘳𝘴𝘵𝘶𝘷𝘸𝘹𝘺𝘻0123456789!@#$%^&*()_-+=?/|'\"`"
    bolditalic = "𝑨𝑩𝑪𝑫𝑬𝑭𝑮𝑯𝑰𝑱𝑲𝑳𝑴𝑵𝑶𝑷𝑸𝑹𝑺𝑻𝑼𝑽𝑾𝑿𝒀𝒁𝒂𝒃𝒄𝒅𝒆𝒇𝒈𝒉𝒊𝒋𝒌𝒍𝒎𝒏𝒐𝒑𝒒𝒓𝒔𝒕𝒖𝒗𝒘𝒙𝒚𝒛0123456789!@#$%^&*()_-+=?/|'\"`"
    mono = "𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿!@#$%^&*()_-+=?/|'\"`"


# LinkedIn "little text" reserved characters — if unescaped, LinkedIn's
# parser stops at the first occurrence and truncates the post.
# Based on: text.replace(/[\(*\)\[\]\{\}<>@|~_]/gm, (x) => "\\" + x)
_LINKEDIN_RESERVED = frozenset(r"()*[]{}<>@|~_")


def escape_linkedin(text: str) -> str:
    """Backslash-escape LinkedIn 'little text' reserved characters.

    Must be called **after** :func:`convert` so that ``*`` and ``_``
    have already been consumed by markdown-to-Unicode conversion and
    won't be escaped unnecessarily.
    """
    return "".join("\\" + c if c in _LINKEDIN_RESERVED else c for c in text)


def convert(md_text: str) -> str:
    """Convert Markdown formatting in *md_text* to Unicode characters.

    Supported patterns:
        ``**bold**``      → bold (mathematical sans-serif bold)
        ``*italic*``      → italic (mathematical serif italic)
        ``***both***``    → bold italic
        `` `mono` ``     → monospace (mathematical sans-serif monospace)

    Unsupported Markdown (headers ``#``, lists ``-``, links, etc.) is
    passed through unchanged.
    """
    result = ""
    mode = Mode.REGULAR
    asterisks = 0

    for i, char in enumerate(md_text):
        if char in Remaps.regular:
            chr_index = Remaps.regular.index(char)
        else:
            result += char
            continue

        match char:
            case "*":
                if i < len(md_text) - 1 and md_text[i + 1] == "*":
                    asterisks = (asterisks + 1) % 4
                else:
                    match mode:
                        case Mode.REGULAR:
                            match asterisks:
                                case 0:
                                    mode = Mode.ITALIC
                                case 1:
                                    mode = Mode.BOLD
                                case 2:
                                    mode = Mode.BOLDITALIC
                        case Mode.ITALIC:
                            match asterisks:
                                case 0:
                                    mode = Mode.REGULAR
                                case 1:
                                    mode = Mode.BOLDITALIC
                                case 2:
                                    mode = Mode.BOLD
                        case Mode.BOLD:
                            match asterisks:
                                case 0:
                                    mode = Mode.BOLDITALIC
                                case 1:
                                    mode = Mode.REGULAR
                                case 2:
                                    mode = Mode.ITALIC
                        case Mode.BOLDITALIC:
                            match asterisks:
                                case 0:
                                    mode = Mode.BOLD
                                case 1:
                                    mode = Mode.ITALIC
                                case 2:
                                    mode = Mode.REGULAR
                    asterisks = 0
            case "`":
                match mode:
                    case Mode.REGULAR:
                        mode = Mode.MONO
                    case Mode.MONO:
                        mode = Mode.REGULAR
            case _:
                match mode:
                    case Mode.REGULAR:
                        result += char
                    case Mode.ITALIC:
                        result += Remaps.italic[chr_index]
                    case Mode.BOLD:
                        result += Remaps.bold[chr_index]
                    case Mode.BOLDITALIC:
                        result += Remaps.bolditalic[chr_index]
                    case Mode.MONO:
                        result += Remaps.mono[chr_index]

    return result
