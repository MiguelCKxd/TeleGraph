KEYS=['Search packs, keywords or an emoji','Search results']
ROWS={
'es':'Buscar packs, palabras clave o un emoji|Resultados de búsqueda',
'ru':'Поиск наборов, ключевых слов или эмодзи|Результаты поиска',
'pl':'Szukaj pakietów, słów kluczowych lub emoji|Wyniki wyszukiwania',
'ca':'Cerca paquets, paraules clau o un emoji|Resultats de la cerca',
'ca-valencia':'Busca paquets, paraules clau o un emoji|Resultats de la busca',
'uk':'Пошук наборів, ключових слів або емодзі|Результати пошуку',
'zh-Hans':'搜索贴纸包、关键词或表情|搜索结果',
'ko':'팩, 키워드 또는 이모지 검색|검색 결과',
'ja':'パック、キーワード、絵文字を検索|検索結果',
'it':'Cerca pacchetti, parole chiave o emoji|Risultati di ricerca',
'pt':'Pesquisar pacotes, palavras-chave ou emoji|Resultados da pesquisa',
'el':'Αναζήτηση πακέτων, λέξεων-κλειδιών ή emoji|Αποτελέσματα αναζήτησης',
'eu':'Bilatu paketeak, gako-hitzak edo emoji bat|Bilaketaren emaitzak',
'gl':'Buscar paquetes, palabras clave ou un emoji|Resultados da busca',
'oc-aran':'Cèrca paquets, paraules clau o un emoji|Resultats dera cèrca',
'an':'Buscar paquetz, parolas clau u un emoji|Resultaus d’a busca',
}
def extend(catalogues):
    for language,row in ROWS.items():
        values=row.split('|')
        if len(values)!=len(KEYS):raise ValueError(language)
        catalogues.setdefault(language,{}).update(zip(KEYS,values))

CONNECTION={
'es':'Conectado','ru':'Подключено','pl':'Połączono','ca':'Connectat','ca-valencia':'Connectat',
'uk':'Підключено','zh-Hans':'已连接','ko':'연결됨','ja':'接続済み','it':'Connesso','pt':'Ligado',
'el':'Συνδέθηκε','eu':'Konektatuta','gl':'Conectado','oc-aran':'Connectat','an':'Connectau'}
KEYS.append('Connected')
for language,value in CONNECTION.items():ROWS[language]+='|'+value
