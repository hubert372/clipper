# Clipper

Obserwuje kilka kanałów Twitch naraz, wykrywa skoki aktywności czatu i wycina
z nagrywanego na żywo streama pionowe klipy 9:16 z napisami.

## Instalacja (Windows)

Otwórz PowerShell i wklej:

```powershell
irm https://raw.githubusercontent.com/hubert372/clipper/main/install.ps1 | iex
```

Komenda instaluje Git, Pythona 3.12 i FFmpeg (jeśli ich nie ma), pobiera aplikację do
`%USERPROFILE%\clipper`, instaluje Streamlink i faster-whisper, tworzy skrót „Clipper”
na pulpicie i uruchamia aplikację we własnym oknie.

## Codzienne użycie

Uruchamiaj skrótem „Clipper” (czyli `start.bat`). Przy każdym starcie aplikacja sama
pobiera najnowszą wersję z GitHuba. Kanały, ustawienia i klipy są w folderze `data`,
którego aktualizacje nie ruszają.

Zamknięcie okna Clippera zatrzymuje nagrywanie i aplikację. Dziennik zapisuje się też
w `data/clipper.log`. Panel w przeglądarce zamiast okna: `python app.py --browser`.

## Jak to działa

- **Streamlink** nagrywa każdy kanał na żywo do `data/recordings`.
- Czat jest czytany anonimowo (bez logowania) i liczony w oknach po 10 s.
- Skok = liczba wiadomości w oknie ≥ średnia z ostatnich 5 minut × czułość
  (i nie mniej niż ustawione minimum). Próg widać na wykresie jako przerywaną linię.
- **FFmpeg** wycina fragment (domyślnie 22 s przed i 8 s po skoku) i kadruje do 1080×1920.
- **Whisper** (faster-whisper) dodaje napisy. Model pobiera się przy pierwszym klipie.
- Gotowe klipy trafiają do `data/clips` i do panelu. Przycisk „Klip teraz” robi klip ręcznie.

## Zakładki

- **Kanały** – dodawanie kanałów, status, wykres czatu, dziennik.
- **Monitor** – duże wykresy czatu wszystkich kanałów z ostatnich 10 minut.
- **Klipy** – galeria z filtrem kanału, sortowaniem po ocenie, pobieraniem i kopiowaniem opisu.
- **Ocena** – punktacja 0–100 (reakcja czatu, początek, mowa, napisy, dźwięk, długość)
  z listą rzeczy do poprawy. Przycisk „Oceń przez AI” wysyła transkrypcję i statystyki
  do API Anthropic (wymaga własnego klucza w Ustawieniach, płatne za każde zapytanie).
- **Edytor** – przycinanie początku i końca, poprawianie słów w napisach, tytuł i hashtagi,
  ponowny render.
- **Statystyki** – klipy na kanał, godziny, powody klipów, najlepsze klipy, miejsce na dysku.
- **Ustawienia** – wykrywanie, słowa-wyzwalacze, styl napisów, powiadomienia (dźwięk,
  webhook Discorda), klucz AI.

## Montaż pod TikToka, Reels i Shorts

- **Haczyk** (opcja kanału, domyślnie włączona): klip ma ok. 18 s i zaczyna się kilka sekund
  przed reakcją czatu. Długość i wyprzedzenie ustawiasz w Ustawieniach.
- **Najpierw puenta, auto-zoom, emotka z czatu, efekty dźwiękowe**: włączane w Opcjach kanału.
- **Strefy bezpieczne**: napisy, tytuł, logo i pasek postępu są trzymane poza obszarami, które
  zasłania interfejs aplikacji. Podgląd z nakładką jest w oknie klipu.
- **Edytor**: tryb wycinania słów (znika też obraz i dźwięk), eksport 16:9, 1:1 i SRT.
- **Klipy**: „Montaż z zatwierdzonych” składa do 8 najlepszych klipów w jeden film.
- **Publikacja**: opisy osobno na Shorts, TikToka i Reels, plan, odhaczanie i wyświetlenia;
  wyniki widać w Statystykach.

## Zarabianie na klipach

- **Wnioski**: po wpisaniu wyświetleń w zakładce Publikacja Clipper liczy, o ile długość klipu,
  styl napisów, efekty, kanał, platforma i pora publikacji podnoszą lub obniżają wyświetlenia,
  i sam przestawia ustawienia na to, co działa. Około co trzeci automatyczny klip powstaje
  w jednym zmienionym wariancie, żeby było co porównywać. Każda zmiana jest w dzienniku Wniosków.
- **Potencjał**: liczba na kafelku klipu to ocena skorygowana o dotychczasowe wyniki; Klipy
  i Publikacja są domyślnie sortowane od najlepszych.
- **Kampanie**: wczytujesz kampanię z linku Content Rewards (AI czyta regulamin), przypisujesz
  kanały, a Clipper pilnuje wymagań, sprawdza klipy pod kątem zasad i liczy szacowany zarobek.
  „Proponowane kampanie” pobiera publiczną listę z Content Rewards.
- **Klipy na telefon**: po włączeniu w Ustawieniach skanujesz kod QR i pobierasz zatwierdzone
  klipy z opisami na telefonie w tej samej sieci Wi-Fi (osobny port, tylko odczyt, tajny adres).

## Start, pauza i opcje kanału

- Przycisk **Pauza / Start** w lewym panelu wstrzymuje i wznawia nagrywanie wszystkich
  kanałów. Obok widać stan, liczbę kanałów na żywo, kolejkę renderu i czas ostatniego klipu.
- Przycisk **Opcje** przy kanale włącza osobno dla niego: układ z kamerką, nagłówek z tytułem,
  pasek postępu, logo, cenzurę przekleństw, wycinanie ciszy, wyróżnianie słów, wyrównanie
  głośności i klip przy skoku głośności. Listy słów i plik logo ustawiasz w Ustawieniach.
- **AI dobierze ustawienia** (pole przy dodawaniu kanału albo przycisk w Opcjach): gdy kanał
  jest na żywo i zbierze ok. 2 minuty czatu, Clipper wysyła do API Anthropic jedną klatkę
  ze streama, tytuł, kategorię i próbkę czatu, a model ustawia czułość, słowa-wyzwalacze,
  język napisów, obszar kamerki i pozostałe opcje kanału. Wymaga klucza API, jedno płatne
  zapytanie na kanał. Wynik można potem poprawić ręcznie w Opcjach.
- W zakładce **Klipy** zatwierdzasz lub odrzucasz nowe klipy (odrzucone są kasowane),
  a zatwierdzone pobierasz jedną paczką ZIP z plikiem `opisy.txt`.

## AI bez klucza API (Claude Code)

W Ustawieniach, w grupie AI, można wybrać „Claude Code (logowanie kontem Claude)”. Clipper
uruchamia wtedy lokalnie zainstalowany program `claude` w trybie `claude -p`, więc zapytania
idą przez Twoje logowanie w Claude Code i liczą się do limitów subskrypcji. Wymaga
zainstalowanego Claude Code i jednorazowego zalogowania (uruchom `claude` w terminalu).
Clipper sam nie loguje do Claude i nie widzi Twoich danych logowania.

Klucz API i webhook są zapisywane lokalnie w `data/config.json`.

## Dobrze wiedzieć

- Pierwsze ~60 s po dodaniu kanału aplikacja zbiera średnią czatu i nie robi klipów.
- Nagranie zajmuje ok. 1,5 GB na godzinę na kanał (720p) i jest usuwane po końcu
  streama, chyba że włączysz „Zachowuj pełne nagrania”.
- Na małych kanałach zmniejsz „Min. wiadomości w oknie”, na dużych zwiększ czułość.
- Napisy na samym procesorze: wybierz model `tiny` lub `base`, jeśli render trwa za długo.
- Klipy z cudzych streamów publikuj tylko wtedy, gdy streamer na to pozwala.
