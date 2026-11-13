# bot.py
import os, sys, json, random, re, time, base64, hashlib, datetime
from pathlib import Path

for _v, _p in (("CURL_CA_BUNDLE", r"C:\certs\cacert.pem"),
               ("SSL_CERT_FILE", r"C:\certs\cacert.pem"),
               ("REQUESTS_CA_BUNDLE", r"C:\certs\cacert.pem")):
    if Path(_p).exists():
        os.environ.setdefault(_v, _p)

from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired, ChallengeRequired, PleaseWaitFewMinutes,
    RateLimitError, FeedbackRequired, MediaError
)

# ---------------- configuração ----------------
POST_URL  = os.environ.get("POST_URL", "https://www.instagram.com/reel/Dfp-LiDxAxX/")
SESSION   = Path("session.json")
STATE     = Path("state.json")
INVALIDAS = Path("mencoes_invalidas.txt")
AMIGOS    = Path("amigos.txt")
LOG       = Path("comentarios.log")
PARAR     = Path("parar.txt")

AUTO = os.environ.get("AUTO") == "1"      # nuvem: não pergunta
DRY  = os.environ.get("DRY")  == "1"      # só gera, não publica
PROXY = os.environ.get("IG_PROXY") or None

META_DIA         = int(os.environ.get("META_DIA", 100))
MIN_POR_HORA     = 12
MAX_POR_HORA     = 16
MENCOES_MIN      = 3
MENCOES_MAX      = 4
REFRESH_POOL     = 30
PAUSA_LONGA_CADA = (10, 15)
PAUSA_LONGA_SEG  = (600, 900)
MAX_FALHAS       = 5

RE_USER = re.compile(r"^[A-Za-z0-9._]{2,30}$")

ABERTURAS = [
    "Boa sorte a todos", "Já estou a imaginar ao volante",
    "Este carro era o meu sonho", "Contem comigo",
    "Não podia deixar passar", "Aqui fica a minha entrada",
    "Que máquina", "Estou a torcer por mim e por vocês",
    "Chaves na mão era já", "Vi o carro e tive de comentar",
]

ADJETIVOS = [
    "incrível", "brutal", "espetacular", "dos sonhos", "lindo",
    "fantástico", "memorável", "irresistível", "perfeito", "fenomenal",
    "soberbo", "deslumbrante", "único",
]

SUBSTANTIVOS = [
    "carro", "viatura", "máquina", "bolide", "automóvel",
    "prémio", "sorteio", "oportunidade", "sonho", "mimo",
]

FRASES = [
    "Fazia-me mesmo falta", "Era o carro da minha vida", "Dedos cruzados",
    "Já imagino a viagem de estreia", "Obrigado pela oportunidade",
    "Fazia o meu dia, o meu ano", "Vale a pena tentar",
    "Estou aqui para o que der e vier", "O primeiro depósito era por minha conta",
]

FECHOS = [
    "Boa sorte a todos", "Aguardo o resultado", "Até ao anúncio",
    "Conto com a sorte", "Vamos ver no que dá", "Um abraço e boa sorte",
]

EMOJIS = [["🍀"], ["🔥"], ["✨"], ["🙌"], ["🚗"], ["💫"], ["❤️"],
          ["🚙"], ["🍀", "🔥"], ["🚗", "🙌"], ["🎯"]]

TEMPLATES = [
    "{ab} {emoji} {adj} {sub}! {frase}. {mencao} {fecho}",
    "{ab}, que {sub} {adj}. {mencao} {frase} {emoji}",
    "{frase} — {adj} {sub}, mesmo. {mencao} {ab}. {emoji}",
    "{ab}! {mencao} {adj} {sub}, sem dúvida. {fecho} {emoji}",
    "{adj} {sub}, {ab}. {frase} {mencao} {emoji}",
    "{ab} {emoji} {mencao} {sub} {adj}, sem palavras. {fecho}",
]


# ---------------- estado ----------------
def hoje():
    return datetime.date.today().isoformat()

def agora():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def load_state():
    base = {"data": hoje(), "contador_dia": 0, "total": 0,
            "hashes": [], "mencoes_usadas": []}
    if not STATE.exists():
        return base
    bruto = STATE.read_text(encoding="utf-8", errors="replace").strip()
    if not bruto:
        return base
    try:
        d = json.loads(bruto)
    except json.JSONDecodeError:
        print("aviso: state.json inválido, a recomeçar")
        return base
    for k, v in base.items():
        d.setdefault(k, v)
    if d["data"] != hoje():
        print(f"novo dia — contador reiniciado (era {d['data']})")
        d["data"] = hoje()
        d["contador_dia"] = 0
        d["mencoes_usadas"] = []
    if len(d["hashes"]) > 6000:
        d["hashes"] = d["hashes"][-5000:]
    return d

def save_state(s):
    tmp = STATE.with_name("state.tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, STATE)

def registar(linha):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{agora()} | {linha}\n")

def load_lista(p):
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]

def marcar_invalida(u):
    with INVALIDAS.open("a", encoding="utf-8") as f:
        f.write(u + "\n")

def h(txt):
    return hashlib.sha1(txt.encode()).hexdigest()[:16]


# ---------------- composição ----------------
def compor(mencoes):
    for _ in range(40):
        txt = random.choice(TEMPLATES).format(
            ab=random.choice(ABERTURAS), adj=random.choice(ADJETIVOS),
            sub=random.choice(SUBSTANTIVOS), frase=random.choice(FRASES),
            fecho=random.choice(FECHOS),
            emoji=" ".join(random.choice(EMOJIS)),
            mencao=" ".join(f"@{m}" for m in mencoes),
        )
        txt = re.sub(r"\s+", " ", txt).strip()
        if 90 <= len(txt) <= 400:
            return txt
    return None

def escolher_mencoes(pool, amigos, state, n):
    esc = []
    if amigos:
        k = random.randint(1, min(2, len(amigos), n))
        esc += random.sample(amigos, k)

    usadas = set(state["mencoes_usadas"])
    disp = [m for m in pool if m not in usadas and m not in esc]
    if len(disp) < (n - len(esc)):
        state["mencoes_usadas"] = []
        disp = [m for m in pool if m not in esc]
    falta = n - len(esc)
    if disp and falta > 0:
        esc += random.sample(disp, min(falta, len(disp)))

    state["mencoes_usadas"].extend(m for m in esc if m not in amigos)
    if len(state["mencoes_usadas"]) > 600:
        state["mencoes_usadas"] = state["mencoes_usadas"][-400:]
    return esc

def pausa_normal():
    seg = int(3600 / random.uniform(MIN_POR_HORA, MAX_POR_HORA))
    return max(90, int(seg * random.uniform(0.85, 1.15)))

def recolher_pool(cl, media_id, me, invalidas, atual):
    novos = 0
    try:
        for c in cl.media_comments(media_id, amount=200):
            u = c.user.username
            if not u or u == me or u in invalidas or u in atual:
                continue
            if not RE_USER.match(u) or u.endswith("."):
                continue
            atual.append(u)
            novos += 1
            if len(atual) >= 2000:
                break
    except Exception as e:
        print("aviso: recolha parcial ->", e)
    return novos


# ---------------- publicação ----------------
def publicar(cl, media_id, txt):
    for _ in range(8):
        try:
            r = cl.media_comment(media_id, txt)
            if r is None:
                raise RuntimeError("resposta vazia")
            return txt
        except (PleaseWaitFewMinutes, RateLimitError, FeedbackRequired):
            raise
        except Exception as e:
            m = re.search(r"@mention\s+([A-Za-z0-9._]+)", str(e))
            if not m:
                raise
            mau = m.group(1).rstrip(".")
            if not mau:
                raise
            marcar_invalida(mau)
            txt = re.sub(rf"@{re.escape(mau)}\b", " ", txt)
            txt = re.sub(r"\s+", " ", txt).strip()
            print(f"    menção inválida removida: {mau}")
            time.sleep(random.randint(4, 9))
    raise RuntimeError("demasiadas menções inválidas")


def main():
    if not SESSION.exists():
        sys.exit("session.json ausente.")

    cl = Client()
    cl.delay_range = [2, 6]
    if PROXY:
        cl.set_proxy(PROXY)
        print("proxy activo")
    cl.load_settings(SESSION)

    try:
        cl.get_timeline_feed()
    except LoginRequired:
        sys.exit("Sessão expirada. Regenera o secret da sessão.")
    except ChallengeRequired:
        sys.exit("Desafio de segurança. Resolve na app e repete.")

    me = cl.account_info().username
    pk = cl.media_pk_from_url(POST_URL.split("?")[0])

    try:
        media = cl.media_info(pk)
    except MediaError as e:
        sys.exit(f"Post inacessível: {e}")

    if getattr(media, "comments_disabled", getattr(media, "commenting_disabled", False)):
        sys.exit("Comentários fechados.")

    invalidas = set(load_lista(INVALIDAS))
    amigos = [a for a in load_lista(AMIGOS) if RE_USER.match(a) and a not in invalidas]

    print(f"conta: {me} | post: {media.user.username} | comentários: {media.comment_count}")
    print(f"amigos: {len(amigos)}")

    pool = []
    recolher_pool(cl, media.id, me, invalidas, pool)
    print(f"pool: {len(pool)}")

    state = load_state()
    print(f"hoje: {state['contador_dia']}/{META_DIA}")

    # ---- geração prévia ----
    propostas, tentativas = [], 0
    while len(propostas) < (2 if (AUTO or DRY) else 1) and tentativas < 60:
        tentativas += 1
        n = random.randint(MENCOES_MIN, MENCOES_MAX)
        if len(pool) + len(amigos) < 1:
            break
        esc = escolher_mencoes(pool, amigos, state, n)
        if not esc:
            break
        txt = compor(esc)
        if not txt or h(txt) in state["hashes"]:
            continue
        if any(txt == p["txt"] for p in propostas):
            continue
        propostas.append({"txt": txt})

    if not propostas:
        sys.exit("Não consegui compor texto.")

    print("\n=== PROPOSTAS ===")
    for i, p in enumerate(propostas, 1):
        print(f"[{i}] {p['txt']}")
    print()

    if not AUTO and not DRY:
        if input("Publicar? (s/n): ").strip().lower() != "s":
            sys.exit("Cancelado.")

    if DRY:
        print("modo seco — nada publicado")
        return

    feitos = falhas = desde_longa = 0
    proxima_longa = random.randint(*PAUSA_LONGA_CADA)

    try:
        while state["contador_dia"] < META_DIA:
            if PARAR.exists():
                print("parar.txt — a terminar")
                break
            if falhas >= MAX_FALHAS:
                print("falhas seguidas — a parar")
                break
            if (state["contador_dia"] + feitos) % REFRESH_POOL == 0 and (state["contador_dia"] + feitos) > 0:
                recolher_pool(cl, media.id, me, invalidas, pool)

            n = random.randint(MENCOES_MIN, MENCOES_MAX)
            esc = escolher_mencoes(pool, amigos, state, n)
            txt = compor(esc)
            if not txt or h(txt) in state["hashes"]:
                continue

            try:
                final = publicar(cl, media.id, txt)
            except PleaseWaitFewMinutes:
                print("bloqueio — 15 min")
                registar("bloqueio")
                falhas += 1
                time.sleep(900)
                continue
            except RateLimitError:
                registar("rate limit")
                break
            except ChallengeRequired:
                registar("desafio")
                print("desafio — resolve na app")
                break
            except Exception as e:
                print("erro:", e)
                registar(f"erro: {e}")
                falhas += 1
                time.sleep(random.randint(20, 45))
                continue

            falhas = 0
            feitos += 1
            desde_longa += 1
            state["contador_dia"] += 1
            state["total"] += 1
            state["hashes"] += [h(txt), h(final)]
            save_state(state)
            print(f"[{state['contador_dia']}/{META_DIA}] {final}")
            registar(final)

            if state["contador_dia"] >= META_DIA:
                break
            if desde_longa >= proxima_longa:
                seg = random.randint(*PAUSA_LONGA_SEG)
                print(f"    pausa longa {seg // 60} min")
                desde_longa = 0
                proxima_longa = random.randint(*PAUSA_LONGA_CADA)
                time.sleep(seg)
            else:
                time.sleep(pausa_normal())

    except KeyboardInterrupt:
        print("\ninterrompido")

    save_state(state)
    registar(f"--- fim sessao={feitos} hoje={state['contador_dia']} ---")
    print(f"\nsessão: {feitos} | hoje: {state['contador_dia']}/{META_DIA}")


if __name__ == "__main__":
    main()
