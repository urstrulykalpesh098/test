PAGES = [
    ("daily", "Daily", "https://claude.ai/artifact/TcxbaSnEiAddmETVgBKL8q"),
    ("ledger", "Ledger", "https://claude.ai/artifact/7jU3VUdjX9x22fNqXoYbCL"),
    ("scorecard", "Scorecard", "https://claude.ai/artifact/M2T7uHbVzqydb38BcrRi8F"),
    ("cfa", "CFA card", "https://claude.ai/artifact/7L9ApUMePWy4aWrt4ZY5kW"),
]

FONT = '<link rel="preconnect" href="https://fonts.googleapis.com">\n<link href="https://fonts.googleapis.com/css2?family=Libre+Franklin:wght@400;500;600;700;800&display=swap" rel="stylesheet">'

EYE = ('<svg viewBox="0 0 34 20" aria-hidden="true"><path d="M1.5 10C7 2.2 27 2.2 32.5 10C27 17.8 7 17.8 1.5 10Z" '
       'fill="none" stroke="currentColor" stroke-width="2"/><circle cx="17" cy="10" r="5.4" fill="var(--lens)"/>'
       '<circle cx="17" cy="10" r="2.2" fill="var(--band)"/></svg>')


def masthead(current, title, stamp, status=True, extra=""):
    links = "".join(
        f'<a href="{u}" target="_blank" rel="noopener"{" aria-current=\"page\"" if k == current else ""}>{n}</a>'
        for k, n, u in PAGES)
    st = '<div class="status" id="status">Loading…</div>' if status else ""
    return (f'<header class="mast"><div class="gut">\n'
            f'<div class="brand"><a class="mark" href="{PAGES[0][2]}" target="_blank" rel="noopener">{EYE}Eye View</a>'
            f'<nav class="pages" aria-label="Desk pages">{links}</nav></div>\n'
            f'<h1>{title}</h1>\n<p class="stamp">{stamp}</p>\n{st}{extra}\n</div></header>\n')


JUMPBAR = '<nav class="jump" aria-label="Sections"><div class="gut" id="jump"></div></nav>\n'

# Builds the sticky section bar from every <section class="sec" data-nav="..."> on the page.
JUMPJS = """<script>
{const j=document.getElementById('jump');if(j){const S=[...document.querySelectorAll('section.sec[data-nav]')];
j.innerHTML=S.map(s=>'<a href="#'+s.id+'">'+s.dataset.nav.replace(/[&<>"]/g,'')+'</a>').join('');
const as=[...j.querySelectorAll('a')];
if('IntersectionObserver' in window){const io=new IntersectionObserver(es=>{es.forEach(e=>{if(e.isIntersecting){as.forEach(a=>{const on=a.getAttribute('href')==='#'+e.target.id;a.classList.toggle('on',on);if(on&&j.scrollWidth>j.clientWidth){j.scrollLeft=a.offsetLeft-24}})}})},{rootMargin:'-15% 0px -75% 0px'});S.forEach(s=>io.observe(s))}}}
</script>"""


def theme():
    return open("desk_theme.css").read()
