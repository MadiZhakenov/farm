"""BR «жиза», партия 4 (айди 10001, ещё 30 отдельно): новые нейтральные текстволлы на португальском, без продукта и брендов.
Темы не повторяют партии 1–3 (neutral_lang_texts, neutral_lang_texts2, neutral_br3_texts). 27 историй разных типов
(история, «ninguém: / eu:», ожидание / реальность, диалог) + 3 списка плашками. Формат — как в neutral_br3_texts."""

from __future__ import annotations

from neutral_br3_texts import _DUR, S

STORIES = [
    S("Respondi na cabeça e achei que tinha mandado 😬",
      "vejo a mensagem.\nrespondo na cabeça.\nachei que tinha mandado.\n\n3 semanas depois:\n\"tá viva?\" 😬",
      "Desculpa, eu respondi na cabeça 👇", "#mensagem", "mensagem, responder, esquecer, amizade", "f"),
    S("Acertar a temperatura do chuveiro 🚿",
      "chuveiro:\ngiro 1 milímetro\npra esquerda: gelo.\ngiro 1 milímetro\npra direita: lava.\no meio-termo\nnão existe 😭",
      "Ninguém acerta de primeira 👇", "#banho", "chuveiro, banho, água quente, água gelada"),
    S("O último pedaço de bolo que ninguém pega 🍰",
      "festa de aniversário.\nsobrou um pedaço de bolo.\nninguém pega.\ntodo mundo quer.\nele fica lá,\nsozinho,\naté o fim da festa 🙂",
      "Educação brasileira nível máximo 👇", "#festa", "bolo, último pedaço, festa, educação"),
    S("O mosquito às 2 da manhã 🦟",
      "apago a luz.\n\"zzzzz\" no meu ouvido.\nacendo a luz:\nsumiu.\napago:\n\"zzzzz\".\n2 da manhã\neu caçando um mosquito\ncom o chinelo 😤",
      "Quem nunca caçou mosquito de madrugada? 👇", "#madrugada", "mosquito, madrugada, insônia, chinelo"),
    S("Terminei a louça e apareceu mais um copo 🧽",
      "terminei a louça.\npia limpa.\nsequei as mãos.\n\naí alguém aparece\ncom um copo 🙂",
      "Sempre tem mais um copo 👇", "#louca", "louça, copo, pia, cozinha"),
    S("\"Você ainda está assistindo?\" 📺",
      "a tv me pergunta:\n\"você ainda\nestá assistindo?\"\n\nsim.\ne não precisava\nme julgar assim 🙂",
      "A tv me julgando 👇", "#serie", "série, tv, maratona, sofá"),
    S("O fone acabou a bateria no começo da caminhada 🎧",
      "comecei a caminhada\ncom a playlist perfeita.\n3 minutos depois:\n\"bateria fraca\".\nagora somos só eu\ne os meus pensamentos 😭",
      "A caminhada mais longa da vida 👇", "#caminhada", "caminhada, fone, bateria, música"),
    S("Esqueci o celular em casa 📱",
      "esqueci o celular em casa.\n5 minutos:\nque liberdade.\n10 minutos:\ne se alguém\nprecisar de mim?\n15 minutos:\nvoltei pra buscar 😅",
      "Quanto tempo você aguenta? 👇", "#celular", "celular, esquecer, liberdade, casa"),
    S("\"Tem 10 centavos?\" 🪙",
      "caixa: \"tem 10 centavos?\"\n\neu procurando\nna bolsa inteira,\nnos bolsos,\nna capinha do celular\ncomo se a minha vida\ndependesse disso 😅",
      "Sempre procuro, nunca tenho 👇", "#troco", "troco, moeda, caixa, mercado"),
    S("Lembrei do aniversário às 23:58 🎂",
      "vi que era aniversário\ndo meu amigo\nàs 23:58.\nmandei:\n\"PARABÉNS!!!\nmuitas felicidades!!\"\ncomo se tivesse lembrado\nde manhã 😬",
      "Ainda conta, tá no prazo 👇", "#aniversario", "aniversário, parabéns, amigo, esquecer"),
    S("Café da manhã de hotel 🥐",
      "café da manhã de hotel:\neu como\ncomo se nunca mais\nfosse ver comida\nna minha vida.\n3 pratos, 2 sucos\ne um bolo na bolsa 😂",
      "Café de hotel é sagrado 👇", "#viagem", "hotel, café da manhã, viagem, comida"),
    S("Escorreguei na rua e continuei como se nada 😅",
      "escorreguei na rua.\nlevantei em 1 segundo,\nolhei em volta\ne continuei andando\ncomo se fosse\ntudo planejado 😅",
      "Ninguém viu. Ninguém. 👇", "#mico", "escorregar, rua, mico, vergonha"),
    S("Toalha molhada em cima da cama 🛏️",
      "toalha molhada\nem cima da cama.\n\nna minha casa\nisso é crime\nsem direito a defesa 💀",
      "Na sua casa também é crime? 👇", "#mae", "toalha molhada, cama, mãe, casa"),
    S("Gravei um áudio, ouvi minha voz e apaguei 🎙️",
      "gravei um áudio\nde 2 minutos.\nouvi a minha voz.\napaguei.\n\nmandei:\n\"oi, tudo bem?\" 🙂",
      "Ninguém gosta de ouvir a própria voz 👇", "#audio", "áudio, voz, mensagem, vergonha"),
    S("8 sacolas, 2 braços, uma viagem só 🛍️",
      "do carro pra casa:\n8 sacolas,\n2 braços,\numa viagem só.\nnem que eu perca\nos dedos 💀",
      "Segunda viagem nunca 👇", "#mercado", "sacolas, mercado, compras, força"),
    S("A porta dizia \"puxe\" 🚪",
      "a porta: \"puxe\".\neu: empurro.\ncom força.\nduas vezes.\n\ne alguém atrás de mim\nolhando tudo 😬",
      "Toda porta me engana 👇", "#mico", "porta, puxe, empurre, mico"),
    S("O pé pra fora do lençol 🦶",
      "o pé pra fora do lençol:\nfresquinho,\nperfeito.\n\nmas e se alguém\npuxar? 😳",
      "Medo que nunca passa 👇", "#dormir", "lençol, pé, dormir, medo"),
    S("Dia de lavar o cabelo = dia perdido 💇‍♀️",
      "dia de lavar o cabelo:\nlavar, hidratar,\ndesembaraçar, secar,\nfinalizar.\n4 horas.\ncompromisso?\nsó amanhã 🙂",
      "Quem tem cabelo grande entende 👇", "#cabelo", "cabelo, lavar o cabelo, hidratação, rotina", "f"),
    S("\"Divide igual?\" e eu só tomei água 🧾",
      "a conta chegou.\nalguém: \"divide igual?\"\n\neu, que só tomei água,\nolhando pra quem pediu\npicanha e sobremesa 🙂",
      "Sempre tem esse amigo 👇", "#amigos", "conta, restaurante, dividir, amigos"),
    S("Chamei a professora de mãe 💀",
      "chamei a professora\nde \"mãe\"\nna frente da sala inteira.\n\nisso foi há 12 anos.\nainda lembro 💀",
      "Quem nunca? 👇", "#escola", "professora, mãe, escola, mico"),
    S("A internet caiu e eu conheci minha família 🙂",
      "a internet caiu.\nfui pra sala.\ndescobri que moro\ncom 4 pessoas\nbem legais 🙂",
      "Prazer, família 👇", "#familia", "internet, família, sala, conversa"),
    S("Encontrar o professor no mercado 😳",
      "encontrar o professor\nno mercado\nde chinelo,\ncomprando pão\nfoi tipo ver\num personagem\nfora do jogo 😳",
      "Professor tem vida própria? 👇", "#escola", "professor, mercado, escola, encontro"),
    S("Ninguém: eu falando com o cachorro com voz de bebê 🐶",
      "ninguém:\n\neu falando\ncom o meu cachorro\ncom voz de bebê\ne perguntando\ncomo foi o dia dele 🥹",
      "Todo dono faz isso 👇", "#cachorro", "cachorro, pet, voz de bebê, amor"),
    S("A receita do vídeo vs a minha 🍳",
      "a receita no vídeo:\nlinda, dourada,\nperfeita.\n\na minha:\nsó o cheiro\ne um susto\nda vizinha 😂",
      "Mostra a sua obra 👇", "#receita", "receita, cozinhar, vídeo, expectativa"),
    S("\"Vou ficar só 5 minutos na festa\" 🎉",
      "eu: \"vou ficar\nsó 5 minutos na festa.\"\n\n4 horas depois:\neu dançando,\nconversando com a tia\ne ajudando a lavar\na louça 😅",
      "Os 5 minutos mais longos 👇", "#festa", "festa, 5 minutos, família, dançar"),
    S("Soluço no meio da prova 😬",
      "soluço\nno meio da prova.\nsilêncio total.\n\"hic.\"\n30 pessoas\nsegurando a risada 😬",
      "Sempre na pior hora 👇", "#escola", "soluço, prova, silêncio, escola"),
    S("A vela cheirosa que eu nunca acendi 🕯️",
      "ganhei uma vela cheirosa.\nnunca acendi.\npra não gastar.\nela tá na estante\nhá 3 anos,\nlinda e intocada 🙂",
      "Tem uma assim na sua casa? 👇", "#casa", "vela, presente, guardar, casa"),
    S("Coisas que a gente faz pra render 🧴",
      ["COISAS QUE A GENTE\nFAZ PRA RENDER:", "1. Água no shampoo\nquando tá acabando.", "2. Cortar o tubo\nda pasta de dente.",
       "3. Virar o frasco\nde cabeça pra baixo.", "4. Raspar o pote\naté brilhar.", "5. Usar o sabonete\naté virar lasca."],
      "Qual você faz? 👇", "#casadebrasileiro", "economia, shampoo, pasta de dente, render"),
    S("Coisas que minha mãe jurava 🙅",
      ["COISAS QUE MINHA\nMÃE JURAVA:", "1. Banho depois de comer\ndá congestão.", "2. Manga com leite\nfaz mal.",
       "3. Abrir a geladeira\nsuado dá gripe.", "4. Cabelo molhado\nna rua resfria.", "5. Fazer careta e bater\no vento: fica assim."],
      "Qual a sua mãe falava? 👇", "#mae", "mãe, mitos, infância, família"),
    S("Coisas que todo professor fala 🏫",
      ["COISAS QUE TODO\nPROFESSOR FALA:", "1. \"Eu vou esperar.\"", "2. \"A prova vai ser\ntranquila.\"",
       "3. \"Isso cai na prova.\"", "4. \"O sinal é pra mim,\nnão pra vocês.\"", "5. \"Não é pra mim,\né pra vocês.\""],
      "Marca seu professor 👇", "#escola", "professor, escola, frases, prova"),
]

assert len(STORIES) == 30, len(STORIES)


def _assign() -> list[str]:
    """Реф (музыка и длина) по объёму текста, ≈ 23 знака в секунду; среди подходящих — наименее использованный; списки — tt_milana."""
    uses = {k: 0 for k in _DUR}
    out = []
    for s in STORIES:
        t = s["text"]
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
