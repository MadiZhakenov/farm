"""Новые нейтральные текстволлы «жиза» для KO и PT, партия 2 (сюжеты 11–20, 10 × 3 версии = 30 на язык): без продуктов и драмы,
не повторяют сюжеты 1–10 из neutral_lang_texts. PT2/KO2 — (реф, текст); META_* — номер сюжета → (тайтлы ×3, описания ×4, хэштеги, теги)."""

_DUR = {"tt_kia": 5.17, "tt_cat": 5.53, "tt_kait": 5.73, "ig_Dcib": 6.21, "ig_DVt8": 6.64, "tt_polyglot": 6.76, "tt_bridget": 7.57,
        "tt_roxanne": 8.95, "tt_sofiia": 9.68}

_PT = [
    "celular com 1%:\neu corro pela casa\ncomo se fosse emergência.\nachei o carregador.\n2 minutos depois\ntiro da tomada\n"
    "porque quero ir pro sofá.\no problema sou eu 🙂",
    "no banho:\neu ganho qualquer discussão.\nfrases perfeitas.\nresposta na ponta da língua.\nna vida real, 3 dias antes:\n\"é… né, você também\" 😭",
    "garçom: \"bom apetite!\"\neu: \"valeu, pra você também!\"\nele só trouxe a comida.\nele não vai comer comigo.\nisso foi há 4 anos.\nainda penso nisso 😭",
    "visita chega em 10 minutos.\ntudo pra debaixo da cama,\ntudo pro armário,\nvela acesa.\nvisita: \"sua casa\nestá sempre tão arrumada!\"\n"
    "por favor, não abre nenhuma porta 🙂",
    "a cadeira do meu quarto:\nninguém nunca sentou nela.\nmas tem\n7 blusas, 3 calças\ne uma vida\nque um dia eu arrumo 🙂",
    "academia: 14 meses pagando.\nquantas vezes eu fui: 3.\ncada ida me custou\nuns 400 reais.\nmas eu não cancelo,\nsegunda eu volto 🙂",
    "alarme às 7.\nalarme às 7:05.\nalarme às 7:10.\nalarme às 7:15.\nacordo às 7:40\ne saio correndo\ncom uma meia na mão 😭",
    "meus pais:\n\"a culpa é do celular.\"\ntambém meus pais:\n14 vídeos por dia\nno grupo da família.\ncom som.\nàs 6 da manhã 🙂",
    "amiga cancela o rolê.\npor fora:\n\"ah não, que pena!\"\npor dentro:\npijama,\nsofá,\nmelhor dia da minha vida 🙂",
    ["COISAS QUE SÓ ADULTO\nENTENDE:", "1. Ficar feliz com\numa esponja nova.", "2. Ficar com sono às 21h\ne ter orgulho disso.",
     "3. \"A gente precisa marcar\"\nquer dizer: daqui a 2 anos.", "4. O dinheiro acabou,\nninguém sabe com o quê.", "5. Fazer barulho estranho\nao levantar."],
]

_KO = [
    "폰 배터리 1%:\n비상사태처럼\n온 집을 뛰어다님.\n충전기 찾았다.\n2분 뒤\n소파 가고 싶어서\n뽑아버림.\n문제는 나야 🙂",
    "샤워할 때 나:\n모든 말싸움에서 이김.\n완벽한 문장.\n사이다 그 자체.\n3일 전 실제 상황:\n\"어… 너도…\" 😭",
    "직원: \"맛있게 드세요!\"\n나: \"네, 맛있게 드세요!\"\n음식만 갖다주신 분인데.\n같이 안 드시는데.\n4년 전 일인데\n아직도 생각나 😭",
    "손님 오기 10분 전.\n전부 침대 밑으로,\n전부 옷장 안으로,\n향초 켜기.\n손님: \"집이 항상\n깨끗하네요!\"\n제발 아무 문도 열지 마 🙂",
    "내 방 의자:\n아무도 앉은 적 없음.\n대신 올려져 있는 것:\n니트 7개, 바지 3개,\n그리고 언젠가 정리할\n내 인생 🙂",
    "헬스장 등록 14개월째.\n간 횟수: 3번.\n한 번 갈 때마다\n약 20만 원.\n그래도 해지는 안 해.\n월요일부터 갈 거니까 🙂",
    "알람 7시.\n알람 7시 5분.\n알람 7시 10분.\n알람 7시 15분.\n7시 40분에 일어나서\n양말 한 짝 들고\n뛰어나감 😭",
    "부모님:\n\"다 핸드폰 때문이야.\"\n역시 부모님:\n가족 단톡에\n하루 영상 14개.\n소리 켜고.\n아침 6시에 🙂",
    "친구가 약속 취소.\n겉으로:\n\"아 진짜 아쉽다!\"\n속으로:\n잠옷 입고,\n소파에 눕고,\n인생 최고의 날 🙂",
    ["어른만 아는 것들:", "1. 새 수세미에\n설레기", "2. 밤 9시에 졸리고\n뿌듯해하기", "3. \"언제 한번 보자\"\n= 2년 뒤",
     "4. 돈이 없어졌는데\n어디 썼는지 모름", "5. 일어날 때\n이상한 소리 내기"],
]


def _assign() -> list[str]:
    """Реф (музыка и длина) по объёму португальского текста, ≈ 23 знака в секунду; среди подходящих — наименее использованный."""
    uses = {k: 0 for k in _DUR}
    out = []
    for t in _PT:
        if isinstance(t, list):
            out.append("tt_milana")
            continue
        need = len(t) / 23
        ok = [k for k, d in _DUR.items() if need <= d <= need + 1.7] or ["tt_sofiia"]
        ref = min(ok, key=lambda k: (uses[k], _DUR[k]))
        uses[ref] += 1
        out.append(ref)
    return out


REFS = _assign()
PT2 = list(zip(REFS, _PT))
KO2 = list(zip(REFS, _KO))

META_PT = {
    11: (["1% de bateria e eu em pânico 🔋", "Corri pela casa atrás do carregador", "2 minutos depois tirei da tomada 🙂"],
         ["Quem mais faz isso? 👇", "O carregador nunca alcança o sofá.", "Bateria em 1% é o meu cardio.", "Marca quem vive assim 👇"],
         ["#humor", "#quemnunca", "#vidareal", "#shorts"], ["celular", "bateria", "carregador", "humor", "quem nunca", "vida real", "relatable", "shorts", "sofá"]),
    12: (["No banho eu ganho qualquer discussão 🚿", "A resposta perfeita veio 3 dias depois", "\"É… né, você também\" 😭"],
         ["Por que a resposta só vem no banho? 👇", "Campeão de debate, mas só no chuveiro.", "Quem nunca ensaiou briga no banho? 👇", "Salva pra próxima discussão 📌"],
         ["#humor", "#quemnunca", "#banho", "#shorts"], ["banho", "discussão", "resposta", "humor", "quem nunca", "vida real", "relatable", "shorts", "pensamentos"]),
    13: (["Garçom: bom apetite! Eu: pra você também 😭", "Isso foi há 4 anos e ainda penso nisso", "Ele só trouxe a comida…"],
         ["Qual mico te persegue até hoje? 👇", "Meu cérebro guarda isso com muito carinho.", "Já aconteceu com você? 👇", "3 da manhã e eu lembrando disso 🙂"],
         ["#humor", "#mico", "#vidareal", "#shorts"], ["garçom", "mico", "vergonha", "restaurante", "humor", "quem nunca", "vida real", "shorts", "relatable"]),
    14: (["Visita chega em 10 minutos 😱", "Sua casa está sempre tão arrumada!", "Por favor, não abre nenhuma porta 🙂"],
         ["Onde vocês escondem a bagunça? 👇", "O armário sabe de tudo.", "A faxina mais rápida do Brasil.", "Marca quem faz igual 👇"],
         ["#humor", "#quemnunca", "#casa", "#shorts"], ["visita", "faxina", "bagunça", "casa", "humor", "quem nunca", "vida real", "shorts", "relatable"]),
    15: (["A cadeira do quarto que ninguém senta 🪑", "7 blusas, 3 calças e uma vida", "Um dia eu arrumo essa cadeira 🙂"],
         ["Sua cadeira também é assim? 👇", "Essa cadeira nunca foi usada pra sentar.", "Não é bagunça, é um sistema.", "Quem tem essa cadeira em casa? 👇"],
         ["#humor", "#quemnunca", "#quarto", "#shorts"], ["cadeira", "roupa", "bagunça", "quarto", "humor", "quem nunca", "vida real", "shorts", "relatable"]),
    16: (["14 meses de academia, fui 3 vezes 🏋️", "Cada treino me custou 400 reais", "Segunda eu volto 🙂"],
         ["Quem mais paga e não vai? 👇", "Sou praticamente sócio da academia.", "Segunda agora vai, confia.", "Marca seu parceiro de academia 👇"],
         ["#humor", "#academia", "#quemnunca", "#shorts"], ["academia", "treino", "segunda", "humor", "quem nunca", "vida real", "relatable", "shorts", "dinheiro"]),
    17: (["Alarme às 7, 7:05, 7:10, 7:15… 😭", "Acordei às 7:40 com uma meia na mão", "Por que eu coloco tantos alarmes?"],
         ["Quantos alarmes você coloca? 👇", "Nenhum desses alarmes me acordou.", "Toda manhã é a mesma corrida.", "Quem nunca saiu correndo assim? 👇"],
         ["#humor", "#quemnunca", "#manhã", "#shorts"], ["alarme", "despertador", "manhã", "atraso", "humor", "quem nunca", "vida real", "shorts", "relatable"]),
    18: (["Meus pais: a culpa é do celular 📱", "14 vídeos por dia no grupo da família", "Com som, às 6 da manhã 🙂"],
         ["O grupo da sua família também é assim? 👇", "Bom dia com figurinha e áudio de 4 minutos.", "Quem manda mais vídeo na sua família? 👇", "Marca aquele tio do grupo 👇"],
         ["#humor", "#família", "#grupodafamilia", "#shorts"], ["pais", "família", "whatsapp", "celular", "humor", "quem nunca", "vida real", "shorts", "relatable"]),
    19: (["Quando a amiga cancela o rolê 🙂", "Por fora: que pena! Por dentro: pijama", "Melhor dia da minha vida"],
         ["Fala a verdade, você também comemora 👇", "Pijama às 19h é o verdadeiro luxo.", "Quem mais torce pra cancelar? 👇", "Manda pra amiga que sempre cancela 👇"],
         ["#humor", "#quemnunca", "#introvertidos", "#shorts"], ["rolê", "cancelar", "amiga", "sofá", "pijama", "humor", "quem nunca", "shorts", "relatable"]),
    20: (["Coisas que só adulto entende 🧽", "Feliz com uma esponja nova", "\"A gente precisa marcar\" = daqui a 2 anos"],
         ["Qual desses é você? 👇", "Virar adulto foi isso.", "A número 4 me pegou.", "Salva e manda pra um adulto cansado 📌"],
         ["#humor", "#vidaadulta", "#quemnunca", "#shorts"], ["vida adulta", "adulto", "dinheiro", "sono", "humor", "quem nunca", "vida real", "shorts", "relatable"]),
}

META_KO = {
    11: (["배터리 1%가 되면 일어나는 일 🔋", "충전기 찾아 온 집을 뛰어다님", "2분 뒤에 뽑아버린 사람 🙂"],
         ["나만 이래요? 👇", "소파까지 닿는 충전기는 왜 없을까.", "배터리 1%는 내 유일한 유산소.", "공감되면 저장 📌"],
         ["#공감", "#일상", "#배터리", "#shorts"], ["공감", "일상", "배터리", "충전기", "핸드폰", "웃긴", "자취", "직장인", "shorts"]),
    12: (["샤워할 때는 말싸움 무패 🚿", "완벽한 대답은 3일 뒤에 떠오른다", "\"어… 너도…\" 😭"],
         ["왜 대답은 샤워할 때 생각날까요? 👇", "샤워실 토론 대회 우승자입니다.", "다들 샤워하면서 연습하죠? 👇", "다음 말싸움을 위해 저장 📌"],
         ["#공감", "#일상", "#샤워", "#shorts"], ["공감", "일상", "샤워", "말싸움", "대답", "웃긴", "직장인", "대학생", "shorts"]),
    13: (["직원분께 맛있게 드세요 해버림 😭", "4년 전 일인데 아직도 생각나", "음식만 갖다주신 분인데…"],
         ["여러분의 흑역사는 뭐예요? 👇", "뇌가 이런 건 왜 안 잊어버릴까.", "이런 적 있는 사람 손 🙋", "새벽 3시에 또 생각남 🙂"],
         ["#공감", "#흑역사", "#일상", "#shorts"], ["공감", "흑역사", "식당", "민망", "일상", "웃긴", "대학생", "직장인", "shorts"]),
    14: (["손님 오기 10분 전 우리 집 😱", "집이 항상 깨끗하네요!", "제발 아무 문도 열지 마 🙂"],
         ["다들 어디에 숨겨요? 👇", "옷장은 모든 걸 알고 있다.", "세상에서 제일 빠른 청소.", "똑같은 사람 태그 👇"],
         ["#공감", "#자취", "#청소", "#shorts"], ["공감", "자취", "청소", "손님", "집", "웃긴", "일상", "대학생", "shorts"]),
    15: (["아무도 앉은 적 없는 내 방 의자 🪑", "니트 7개, 바지 3개, 그리고 내 인생", "언젠가 정리할 거야 🙂"],
         ["여러분 의자도 이래요? 👇", "이 의자는 앉으라고 있는 게 아니에요.", "이건 나름의 시스템입니다.", "우리 집에도 있다 하면 하트 ❤️"],
         ["#공감", "#자취", "#일상", "#shorts"], ["공감", "자취", "의자", "옷", "정리", "웃긴", "일상", "직장인", "shorts"]),
    16: (["헬스장 14개월, 간 횟수 3번 🏋️", "한 번 갈 때마다 20만 원", "월요일부터 갈 거니까 🙂"],
         ["돈만 내는 사람 또 있죠? 👇", "거의 헬스장 투자자입니다.", "이번 월요일은 진짜예요.", "같이 안 가는 친구 태그 👇"],
         ["#공감", "#헬스", "#다이어트", "#shorts"], ["공감", "헬스장", "운동", "월요일", "다이어트", "웃긴", "일상", "직장인", "shorts"]),
    17: (["알람 7시, 7시 5분, 7시 10분… 😭", "7시 40분에 양말 들고 뛰어나감", "알람은 왜 이렇게 많이 맞출까"],
         ["알람 몇 개 맞춰요? 👇", "그 많은 알람 중에 나를 깨운 건 없다.", "매일 아침이 달리기 시합.", "지각 자주 하는 친구 태그 👇"],
         ["#공감", "#직장인", "#아침", "#shorts"], ["공감", "알람", "아침", "지각", "직장인", "대학생", "웃긴", "일상", "shorts"]),
    18: (["부모님: 다 핸드폰 때문이야 📱", "가족 단톡에 하루 영상 14개", "소리 켜고, 아침 6시에 🙂"],
         ["여러분 가족 단톡도 이래요? 👇", "좋은 아침 이미지는 매일 도착합니다.", "우리 집에서 영상 제일 많이 보내는 사람은? 👇", "부모님께는 비밀 🤫"],
         ["#공감", "#가족", "#단톡", "#shorts"], ["공감", "가족", "부모님", "단톡", "카톡", "웃긴", "일상", "핸드폰", "shorts"]),
    19: (["친구가 약속을 취소했을 때 🙂", "겉으로는 아쉽다, 속으로는 잠옷", "인생 최고의 날"],
         ["솔직히 다들 좋아하잖아요 👇", "저녁 7시 잠옷은 진짜 사치.", "취소되길 기도한 사람 손 🙋", "맨날 취소하는 친구에게 공유 👇"],
         ["#공감", "#집순이", "#일상", "#shorts"], ["공감", "약속", "취소", "집순이", "잠옷", "소파", "웃긴", "일상", "shorts"]),
    20: (["어른만 아는 것들 🧽", "새 수세미에 설레는 나이", "\"언제 한번 보자\" = 2년 뒤"],
         ["몇 개나 해당돼요? 👇", "어른이 된다는 건 이런 거였다.", "4번에서 울었어요.", "피곤한 어른에게 공유 📌"],
         ["#공감", "#어른", "#일상", "#shorts"], ["공감", "어른", "직장인", "돈", "수면", "웃긴", "일상", "현실", "shorts"]),
}
