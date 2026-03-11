import re

class switch(object):
    def __init__(self, value):
        self.value = value
        self.fall = False

    def __iter__(self):
        """Return the match method once, then stop"""
        yield self.match
        raise StopIteration

    def match(self, *args):
        """Indicate whether to enter a case suite"""
        if self.fall or not args:
            return True
        elif self.value in args:  # changed for v1.5, see below
            self.fall = True
            return True
        else:
            return False


def humanize_time(secs):
    try:
        mins, secs = divmod(secs, 60)
    except:
        mins = 0
        secs = 0
    try:
        hours, mins = divmod(mins, 60)
    except:
        hours = 0
        mins = 0
    return '%02d:%02d:%02d' % (hours, mins, secs)

def normalize_name(name: str, istitle: bool=False):
    # Normalize a track/album name while preserving meaningful numbers
    # e.g., keep 'Route 66', 'Interlude No. 1', '715'
    # but remove leading track numbers like '05-' and edition phrases like '20th Anniversary Edition'
    orgname = name

    # 1) Remove leading track numbers/prefixes (but keep pure numeric titles like '715')
    # Examples removed: '01 - Title', '05-Title', '7. Title', '12 Title'
    if istitle:
        name = re.sub(r'^(?:\s*(?:\d{1,3}\s*[-_.]\s*|\d{1,2}\s+))', '', name)

    # 2) Remove explicit edition/anniversary phrases that include numbers, but do not touch other numbers
    # Examples removed: '20 Anniversary', '10th Anniversary Edition', '30th edition', '2nd version'
    edition_phrase_patterns = [
        r'(?i)\b\d{1,4}(?:st|nd|rd|th)?\s+anniversary(?:\s+edition)?\b',
        r'(?i)\b\d{1,4}(?:st|nd|rd|th)?\s+edition\b',
        r'(?i)\b\d{1,4}(?:st|nd|rd|th)?\s+version\b',
    ]
    for pat in edition_phrase_patterns:
        name = re.sub(pat, ' ', name)

    # 3) Remove remastered and similar edition-related terms (optionally followed by a year)
    remastered_pattern = (
        r'(?i)\b(?:remaster(?:ed)?|re-?master(?:ed)?|reissue(?:d)?|anniversary|bonus|deluxe|special|expanded|edition|version)\b\s*(?:\d{2,4})?'
    )
    name = re.sub(remastered_pattern, ' ', name)

    # 4) Remove content within brackets and parentheses (often holds edition/live info)
    def remove_brackets(text):
        prev_text = ""
        while prev_text != text:
            prev_text = text
            text = re.sub(r'\[\[[^\[\]]*\]\]', ' ', text)  # [[...]]
            text = re.sub(r'\([^()]*\)', ' ', text)            # (...)
        text = re.sub(r'[\[\]\(\)]', ' ', text)
        return text

    name = remove_brackets(name)

    # 5) Cleanup extra whitespace and separators left after removals
    name = re.sub(r'\s+', ' ', name).strip(' -_').strip()

    return name

if __name__ == '__main__':
    print(normalize_name('150'))

