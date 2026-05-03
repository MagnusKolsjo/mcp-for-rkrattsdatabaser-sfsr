# mcp-for-rkrattsdatabaser-sfsr

En MCP-server som ger MCP-kompatibla AI-verktyg tillgång till Regeringskansliets
Svensk författningssamlings register (SFSR) — det strukturerade ändringsregistret
för svensk lagstiftning.

Med servern kan du följa ändringskedjan för en lag från gällande rätt tillbaka till
ursprungsproposition på paragrafnivå: vem ändrade vad, när, och med stöd av vilken
proposition.

## Vad verktyget gör

- **Hämtar hela ändringshistoriken** för en lag — alla ändrings-SFS med ikraftträdandedatum,
  berörda paragrafer och förarbeten (proposition, betänkande, riksdagsskrivelse)
- **Filtrerar på paragrafnivå** — visar bara de ändrings-SFS som berör en specifik paragraf,
  t.ex. "2 kap. 8 §"
- **Följer ändringskedjan bakåt** — returnerar de senaste kedjeled i omvänd kronologisk
  ordning med propositionsreferenser för vidare uppslag
- **Hanterar EU-kopplingar** — identifierar ändringar som genomför EU-direktiv via
  CELEX-nummer

Data hämtas från beta.rkrattsbaser.gov.se (Elasticsearch-API, primärkälla) med
automatisk fallback till HTML-skrapning av rkrattsbaser.gov.se om API:et inte svarar.
Resultaten cachelagras lokalt för snabb återanvändning.

## Krav

- Python 3.11 eller senare
- Beroenden enligt `requirements.txt`
- PostgreSQL (rekommenderas) eller SQLite (inget extra att installera)
- Ingen API-nyckel krävs — SFSR är öppet tillgängligt

## Installation

Klona repot och installera beroenden:

```bash
git clone https://github.com/MagnusKolsjo/mcp-for-rkrattsdatabaser-sfsr.git
cd mcp-for-rkrattsdatabaser-sfsr
pip install -r requirements.txt
```

Kopiera konfigurationsmallen och fyll i dina värden:

```bash
cp config.example.env .env
```

Initiera databasen:

```bash
python db/init_db.py
```

## Konfiguration

All konfiguration sker via `.env`-filen. Kopiera `config.example.env` till `.env` och justera:

| Variabel | Standardvärde | Beskrivning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///sfsr_cache.db` | PostgreSQL- eller SQLite-anslutning |
| `SFSR_BACKEND` | `api` | `api` (primär) eller `html` (fallback) |
| `SFSR_CACHE_TTL_HOURS` | `24` | Hur länge cachad data anses giltig (timmar) |
| `SFSR_API_URL` | `https://beta.rkrattsbaser.gov.se/…` | URL till Elasticsearch-API:et |
| `SFSR_BASE_URL` | `https://rkrattsbaser.gov.se/sfsr` | URL till HTML-sajten (fallback) |
| `MCP_TRANSPORT` | `stdio` | `stdio` (lokal) eller `http` (hostad) |

**PostgreSQL** (rekommenderas — data isoleras i schemat `sfsr`):
```env
DATABASE_URL=postgresql://anvandare:losenord@localhost:5432/riksdag
```

**SQLite** (ingen serverinstallation krävs):
```env
DATABASE_URL=sqlite:///sfsr_cache.db
```

## Körning

Starta MCP-servern i stdio-läge (standard för lokal användning):

```bash
python mcp_server.py
```

Starta i HTTP-läge (för hostad driftsättning):

```bash
MCP_TRANSPORT=http python mcp_server.py
```

I HTTP-läget rekommenderas Bearer-token-autentisering via `MCP_API_KEY`. Generera
en nyckel med:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Konfiguration av MCP-klient

Servern fungerar med alla AI-verktyg som stöder MCP-protokollet.
Nedan visas ett konfigurationsexempel för Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "sfsr": {
      "command": "python",
      "args": ["/absolut/stig/till/mcp_server.py"]
    }
  }
}
```

Starta om MCP-klienten efter konfigurationsändringen.

## Tillgängliga verktyg

| Verktyg | Beskrivning |
|---|---|
| `sfsr_get_law_history` | Hämtar hela ändringshistoriken för en lag |
| `sfsr_get_paragraph_history` | Filtrerar ändringar som berör en specifik paragraf |
| `sfsr_trace_chain` | Följer ändringskedjan bakåt med propositionsreferenser |

### sfsr_get_law_history

```
sfsr_get_law_history(sfs_nr: str, inkludera_historiska: bool = False)
```

Hämtar alla ändrings-SFS för en lag, kronologiskt sorterade. Returnerar metadata
om grundlagen (rubrik, ikraftträdandedatum, CELEX-nummer) samt för varje ändring:
ändrings-SFS, ikraftträdandedatum, berörda paragrafer, proposition, betänkande,
riksdagsskrivelse och CELEX-nummer.

Exempel: `sfsr_get_law_history("1993:1617")` returnerar alla ändringar av ordningslagen.

### sfsr_get_paragraph_history

```
sfsr_get_paragraph_history(sfs_nr: str, paragraf: str)
```

Filtrerar ändringshistoriken till poster som berör en specifik paragraf.
Hämta först hela historiken med `sfsr_get_law_history` för att se hur paragraferna
är betecknade i SFSR.

Exempel: `sfsr_get_paragraph_history("1993:1617", "2 kap. 8 §")`

### sfsr_trace_chain

```
sfsr_trace_chain(sfs_nr: str, paragraf: str = None, djup: int = 5)
```

Returnerar de senaste `djup` ändringarna i omvänd kronologisk ordning (nyast först).
Propositionsreferenserna kan slås upp vidare med `rd_get_document` i
[riksdagens API-server](https://github.com/MagnusKolsjo/mcp-for-riksdagens-oppna-data).

## Datakälla

SFSR (Svensk författningssamlings register) är Regeringskansliets auktoritativa
register över ändringshistoriken för varje SFS-nummer. Data är offentlig
information och kan fritt användas.

Primärkälla: `beta.rkrattsbaser.gov.se` (Elasticsearch-API)
Fallback: `rkrattsbaser.gov.se` (HTML-skrapning med BeautifulSoup4)

## Utforskningsskript

Två hjälpskript ingår för att utforska och verifiera datakällorna:

```bash
python 01_explore_sfsr.py      # Utforskar HTML-strukturen på rkrattsbaser.gov.se
python 02_explore_sfsr_api.py  # Utforskar och verifierar Elasticsearch-API:et
```

## Kända begränsningar

- **Förarbeten kan saknas** för vissa ändrings-SFS — API:et returnerar inte alltid
  proposition och betänkande, särskilt för ikraftträdandebestämmelser
- **Ikraftträdandedatum kan saknas** för ändringar som enbart ändrar
  ikraftträdandebestämmelser för andra paragrafer
- **HTML-fallbacken** kan behöva anpassas om rkrattsbaser.gov.se ändrar layout
- **API-URL:en** innehåller `beta.` — om beta-sajten ersätter produktionssajten
  behöver `SFSR_API_URL` uppdateras i `.env` (troligen tas `beta.` bort)

## Licens

[AGPLv3](LICENSE)

SFSR-data är offentlig information från Regeringskansliet och kan fritt användas
och distribueras.
