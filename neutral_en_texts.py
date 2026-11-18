"""Нейтральные текстволлы «жиза» на английском: 100 разных сюжетов × 1 версия (как de_neutral_120: бытовые узнаваемые
ситуации, без продуктов и без драмы). EN — (реф по длине текста, текст); TITLES — тайтл YouTube на сюжет."""

_DUR = {"tt_kia": 5.17, "tt_cat": 5.53, "tt_kait": 5.73, "ig_Dcib": 6.21, "ig_DVt8": 6.64, "tt_polyglot": 6.76, "tt_bridget": 7.57,
        "tt_roxanne": 8.95, "tt_sofiia": 9.68}

_S = [
    ("me at 10pm vs me at 3am", "me at 10pm:\ntonight i'm sleeping early.\nme at 3am:\nwatching a video\nof how soap is made.\nalarm in 4 hours.\njust me? 🙂"),
    ("fridge full, nothing to eat 😭", "opened the fridge 5 times.\nnothing to eat.\nopened it again\nin case something appeared.\nmom: the fridge is full!\nme: full of ingredients,\nnot food 😭"),
    ("20 minutes for one text", "spent 20 minutes\non one text.\ntyped, deleted,\nretyped, read it 3 times.\nsent it.\nmy friend replied:\n\"ok\"\nnow i'm analyzing the ok"),
    ("new life starts monday (again)", "every sunday:\nnew life starts monday.\ngym, salad,\nbed by 11.\nmonday, 7am:\nsnooze 4 times\nand pizza for lunch.\nthere's always next monday 🙂"),
    ("just went in for milk", "went to the store\njust for milk.\ncame out with:\na candle, socks, chips,\na plant and a new mug.\nmilk? forgot it.\ngoing back 😭"),
    ("tracking my package 12 times a day", "ordered something online\nand checked the tracking\n12 times a day.\nit finally came.\nripped it open at the door.\n…it's socks.\nstill excited 🙂"),
    ("\"on my way\" from the shower", "friend: \"almost there!\"\nreality: still in the shower.\nme: waiting 30 min at the café.\nbut let's be honest,\ni've also texted \"on my way\"\nwhile doing my mascara 🙂"),
    ("my saved folder vs reality", "my saved folder:\n300 recipes,\n120 home workouts,\n40 \"learn spanish in 30 days\".\nwhat i actually did:\nnothing.\nbut it's all saved 🙂"),
    ("mom: are you eating well?", "mom calls:\n\"are you eating well?\"\nme at 11pm with instant noodles:\n\"of course mom,\nveggies, salad, everything\" 🙂"),
    ("phone at 1% panic", "phone at 1%:\nrunning around the house\nlike it's an emergency.\nfound the charger.\n2 minutes later\ni unplug it\nto lie on the couch.\ni'm the problem 🙂"),
    ("i win every argument in the shower", "in the shower:\ni win every argument.\nperfect comebacks.\nso quick, so smart.\nin real life, 3 days ago:\n\"uh… yeah, you too\" 😭"),
    ("\"enjoy your meal\" \"you too\"", "waiter: \"enjoy your meal!\"\nme: \"thanks, you too!\"\nhe's not eating.\nhe just brought the food.\nthat was 4 years ago.\nstill think about it 😭"),
    ("guests in 10 minutes", "guests in 10 minutes.\neverything under the bed,\neverything in the closet,\nlight a candle.\nguest: \"your place\nis always so tidy!\"\nplease don't open any doors 🙂"),
    ("the chair in my bedroom", "the chair in my bedroom:\nnobody has ever sat on it.\nbut it holds\n7 sweaters, 3 jeans\nand a life\ni'll organize someday 🙂"),
    ("gym membership math", "gym membership: 14 months.\ntimes i went: 3.\nthat's about $90 per visit.\nbut i'm not cancelling,\ni'm going back monday 🙂"),
    ("my 5 alarms", "alarm at 7.\nalarm at 7:05.\nalarm at 7:10.\nalarm at 7:15.\nwoke up at 7:40\nand ran out the door\nholding one sock 😭"),
    ("parents vs phones", "my parents:\n\"phones ruin everything.\"\nalso my parents:\n14 videos a day\nin the family chat.\nwith sound.\nat 6am 🙂"),
    ("when plans get cancelled", "friend cancels our plans.\nme on the outside:\n\"oh no, that's so sad!\"\nme on the inside:\npajamas on,\ncouch,\nbest day of my life 🙂"),
    ("one more episode", "\"one more episode\n and then bed.\"\n4 episodes later\nthe show asks\nif i'm still watching.\nyes. i am.\ndon't judge me 🙂"),
    ("my screen time report", "phone: your screen time\nwas up 23% this week.\nme: that's not true.\nalso me:\n9 hours a day\nwatching other people\nclean their kitchens 😭"),
    ("i'll just rest my eyes", "\"i'll just rest my eyes\nfor 5 minutes.\"\nwoke up 3 hours later,\nconfused,\nnot sure what year it is\nor who i am 😭"),
    ("cleaning while procrastinating", "need to do one thing.\ninstead i:\ncleaned the whole room,\nreorganized my closet,\ndescaled the kettle.\nthe one thing?\ntomorrow 🙂"),
    ("waving at someone who wasn't waving at me", "someone waved.\ni waved back.\nthey were waving\nat the person behind me.\nnow i live here,\nin this moment,\nforever 😭"),
    ("the \"we should hang out\" lie", "\"we should hang out soon!\"\n\"yes, definitely!\"\nboth of us know\nthis will never happen.\nand that's okay 🙂"),
    ("my cart vs my bank account", "online shopping:\nadded 14 things to cart.\nsaw the total.\nremoved 13.\nbought nothing.\nfelt like i saved $300 🙂"),
    ("pretending to text when alone", "standing alone\nsomewhere for 10 seconds:\nphone out immediately.\nnot texting anyone.\njust scrolling my own\nsettings 🙂"),
    ("me cooking vs the recipe", "recipe: 20 minutes.\nme: 1 hour 40 minutes,\n6 dirty pans,\nthe smoke alarm\nand a sandwich\nfor dinner 😭"),
    ("reading the text again after sending", "sent a text.\nread it again.\nread it again.\nfound a typo.\ntoo late.\nthinking about it\nfor the rest of the day 🙂"),
    ("taking 3 days to reply", "friend: sends a voice message.\nme: i'll listen later.\n3 days later:\n\"omg sorry i just saw this!!\"\ni saw it 3 days ago 🙂"),
    ("what i eat when home alone", "home alone for the evening.\ndinner:\ncereal.\nfrom the box.\nstanding at the counter.\nliving my best life 🙂"),
    ("every outfit is \"nothing to wear\"", "closet: full.\nchair: full.\nme: i have nothing to wear.\nwore the same hoodie\nfor the 4th day in a row 🙂"),
    ("me at the doctor", "doctor: \"how much water\ndo you drink?\"\nme: \"like 2 liters a day.\"\nreality:\n1 coffee\nand a sip of my friend's lemonade 😭"),
    ("the 2-minute task i avoided for months", "a task that takes 2 minutes.\ni avoided it\nfor 4 months.\nfinally did it.\n2 minutes.\nwhy am i like this 😭"),
    ("adult life is just laundry", "being an adult:\ndo laundry.\nfold laundry.\nput it on the chair.\nwear it from the chair.\ndo laundry again 🙂"),
    ("me when someone says \"we need to talk\"", "boss: \"got a minute?\nwe need to talk.\"\nmy brain:\nreplays every mistake\nsince 2009.\nboss: \"do you want\na coffee?\" 😭"),
    ("saving money starts tomorrow", "me: i'm saving money now.\nalso me:\nbuys a $7 coffee\nbecause it was a hard morning.\nit was 9am 🙂"),
    ("airport me vs normal me", "normal me: late everywhere.\nairport me:\narrives 4 hours early,\nchecks passport 30 times,\nstands at the gate\nbefore boarding opens 🙂"),
    ("unread notifications", "my phone:\n2,847 unread emails.\n96 unread messages.\nme opening one app:\nto check the weather.\nit's raining.\nclosing the app 🙂"),
    ("the wifi password hunt", "friend: \"what's the wifi password?\"\nme: \"it's on the router.\"\nrouter: behind the tv,\nunder 4 cables,\nin font size 2 😭"),
    ("cleaning my room in 5 minutes", "mom: \"clean your room.\"\nme: shoves everything\ninto one drawer.\nthe drawer won't close.\nthe room looks perfect 🙂"),
    ("when the barista spells my name", "barista: \"name?\"\nme: \"anna.\"\ncup says: \"hannah.\"\ni'm hannah now.\ni've accepted it 🙂"),
    ("me trying to be productive", "plan for today:\n10 tasks.\ndone today:\nmade a to-do list\nfor tomorrow.\nproductive day 🙂"),
    ("ordering food on the phone", "me before calling\nto order food:\nrehearse 4 times.\nme on the call:\n\"hi yes can i\nhave the… uh…\nthe food\" 😭"),
    ("the free sample walk", "grocery store free samples:\ntried one.\nwalked away.\ncame back\nin a different direction\nso she wouldn't recognize me.\nshe did 😭"),
    ("my plants and me", "bought a plant.\nwatered it every day.\nit died.\nbought another one.\nforgot about it for a month.\nit's thriving.\nwhat does it want from me 🙂"),
    ("when you finally get comfortable", "finally comfortable in bed.\nperfect blanket position.\nperfect pillow.\nlight is still on.\nlight stays on 🙂"),
    ("the group project member", "group project:\n4 people.\n1 person does everything.\nif you don't know who it is…\nit's you 🙂"),
    ("buying a planner", "january:\nbought a beautiful planner.\nwrote in it for 3 days.\nfound it in november.\nbrand new.\nbuying a new one 🙂"),
    ("me after one workout", "went to the gym once.\nnow i'm checking the mirror\nevery 5 minutes\nfor abs.\nnothing yet.\ngiving it till tomorrow 🙂"),
    ("me pretending to understand", "someone explains something\nfor 5 minutes.\nme: \"ohhh, yeah, totally.\"\nme inside:\nno idea.\ntoo late to ask now 🙂"),
    ("the 8 hours of sleep myth", "need 8 hours of sleep.\nin bed at 11.\nscrolling till 2.\nalarm at 6.\n\"why am i so tired?\" 😭"),
    ("when someone takes the last slice", "the last slice of pizza.\neveryone politely\npretending they don't want it.\n20 minutes pass.\nstill there.\ni take it.\nno regrets 🙂"),
    ("trying to open a package", "package arrives.\nno scissors.\nused my keys,\nmy teeth,\na spoon\nand all my patience.\nthe scissors were inside 😭"),
    ("me after saying i'm fine", "\"how are you?\"\n\"good, you?\"\ni've had 3 hours of sleep,\n4 coffees\nand cried at an ad.\nbut good 🙂"),
    ("parallel parking with people watching", "parallel parking\nwith nobody around:\nperfect in one try.\nparallel parking\nwith 3 people watching:\n14 attempts\nand i drove away 😭"),
    ("forgetting why i came into the room", "walked into the kitchen.\nstood there.\nforgot why i came.\nwent back to the couch.\nremembered.\nit was the phone\nin my hand 🙂"),
    ("i'll remember it, no need to write it down", "\"i'll remember it,\nno need to write it down.\"\n5 seconds later:\nforgot.\nit was important.\ni'll never know what it was 😭"),
    ("my bank account after the weekend", "friday me:\n\"treat yourself!\"\nmonday me:\nchecking my bank account\nwith one eye open.\n$12 left until payday 😭"),
    ("small talk in the elevator", "elevator with a neighbor.\n10 floors.\nme: \"crazy weather, huh?\"\nthem: \"yeah.\"\n8 more floors\nof silence 🙂"),
    ("when the song you love comes on in a store", "store plays my favorite song.\nme: casually mouthing\nevery word\nin the cereal aisle,\npretending i'm in a music video 🙂"),
    ("my sleep schedule on vacation", "vacation plan:\nwake up early,\nsee everything.\nvacation reality:\nwoke up at 1pm,\nlunch, nap,\nsunset, bed 🙂"),
    ("trying a new hobby", "new hobby: painting.\nbought all the supplies.\n$150 later\npainted one tree.\nit looks like broccoli.\nnew hobby: knitting 🙂"),
    ("the email i sent at 3am", "3am me:\nwrites a long,\nheartfelt email.\n9am me reading it:\nwho let her\nnear a keyboard 😭"),
    ("cancelling a subscription", "free trial: 7 days.\nset a reminder to cancel.\nignored the reminder.\npaying for it\nfor 8 months now.\nnever used it once 🙂"),
    ("me when someone says \"let me see your photos\"", "\"let me see your photos!\"\nme handing over my phone,\nholding my breath,\nswiping for them\nso they don't see\nthe 400 screenshots 😭"),
    ("eating healthy for one day", "ate a salad for lunch.\nfelt amazing.\nrewarded myself\nwith a cookie.\nthen 4 cookies.\nthe salad was a lie 🙂"),
    ("me during a power outage", "power goes out.\nfirst thought:\nwhat do i do now?\nsecond thought:\ni'll scroll on my phone.\nphone at 6% 😭"),
    ("introvert weekend plans", "friday:\n\"what are your weekend plans?\"\nme: \"oh, a few things.\"\nthe things:\nblanket,\nsnacks,\nnot leaving the house 🙂"),
    ("me after a haircut", "hairdresser: \"do you like it?\"\nme: \"i love it!!\"\nme at home:\nstaring in the mirror\nfor 2 hours,\nwaiting for it to grow 😭"),
    ("walking into the wrong class", "first day.\nwalked into the room.\nsat down.\nteacher starts talking.\nwrong room.\nstayed for the whole hour\nbecause i'm too shy to leave 😭"),
    ("the sock that disappeared", "put 2 socks\nin the washing machine.\ntook out 1 sock.\nwhere did it go?\nwhat is the machine doing\nwith all these socks 🙂"),
    ("me reading terms and conditions", "terms and conditions:\n47 pages.\nme:\nscrolled to the bottom,\nchecked the box,\nagreed to give away\nmy firstborn probably 🙂"),
    ("waiting for the microwave", "microwave: 1 minute.\nme: standing in front of it\nfor the whole minute,\nstaring,\nlike it's a movie 🙂"),
    ("me at a restaurant reading the menu", "read the whole menu.\n40 options.\nthought about each one.\nordered\nthe same thing\ni always order 🙂"),
    ("when you hear your own voice in a video", "hearing my own voice\nin a video:\n\"is that what i sound like?\"\nturning it off.\nnever speaking again 😭"),
    ("putting the kettle on 3 times", "put the kettle on.\nforgot.\nput it on again.\nforgot.\nthird time.\ncoffee finally ready at 2pm 🙂"),
    ("my phone in my hand while i search for it", "searching for my phone\nfor 5 minutes.\nunder the pillows,\nin the kitchen,\nin my bag.\nusing the flashlight.\nof my phone 😭"),
    ("rain plans", "it's raining.\ncancelled all plans.\nmade tea,\nblanket,\nwindow,\nrain sounds.\nhonestly the best day of the week 🙂"),
    ("the online meeting", "online meeting:\ncamera off.\nme in pajamas,\neating cereal,\nhalf asleep.\nboss: \"any questions?\"\nme, unmuting: \"…no\" 🙂"),
    ("buying groceries hungry", "never go grocery shopping\nhungry.\nwent hungry.\nbought:\n3 kinds of chips,\na cake,\nfrozen pizza\nand no actual food 😭"),
    ("my overthinking at night", "brain at 2am:\nremember that thing\nyou said in 2014?\nlet's think about it\nfor 3 hours.\nme: please let me sleep 😭"),
    ("the shoes that looked comfortable", "new shoes:\nso comfortable in the store.\n20 minutes outside:\nblisters everywhere.\nwalking home barefoot\nwith dignity 🙂"),
    ("me being polite to the gps", "gps: \"turn left.\"\nme: \"thank you.\"\ngps: \"recalculating.\"\nme: \"sorry, sorry.\"\napologizing to a robot\nfor 40 minutes 🙂"),
    ("when someone sings happy birthday to you", "people singing\nhappy birthday to me:\nwhere do i look?\nwhat do i do with my hands?\nsmiling at the cake\nlike it's a stranger 😭"),
    ("my laptop's 40 open tabs", "my laptop:\n43 tabs open.\nall important.\nno idea which one\nis playing music.\nclosing nothing 🙂"),
    ("taking a photo of the sky", "beautiful sunset.\ntook 47 photos.\nall look the same.\nnone look like real life.\nnever look at them again.\nwill do it again tomorrow 🙂"),
    ("me trying to stay awake in class", "class at 8am:\nhead on my hand,\neyes closing,\nhead slips,\neveryone hears it.\nawake now.\nforever 😭"),
    ("the last day of the weekend", "sunday 6pm:\nthe weekend\nwas 5 minutes long.\nmonday is coming.\nwhere did saturday go?\nwho took it 😭"),
    ("cooking pasta for one", "cooking pasta for one.\nputs in a normal amount.\nit's enough\nfor a family of 6.\neating pasta\nfor 4 days 🙂"),
    ("trying to be quiet at night", "coming home late,\ntrying to be quiet.\nthe floor: creaks.\nthe door: creaks.\nthe keys: fall.\nthe dog: barks.\neveryone: awake 😭"),
    ("the spider in my room", "saw a spider.\nlooked away for 1 second.\nit's gone.\nnow i live\nwith a spider somewhere\nin my room.\ngood night 😭"),
    ("me when someone says \"no rush\"", "\"no rush,\nwhenever you can!\"\nme:\ndrops everything,\nfinishes it in 4 minutes\nand sends it 🙂"),
    ("me pretending to be busy at work", "boss walks by.\nme: typing very fast,\nserious face,\nclicking random things.\nwas reading\nabout penguins 🙂"),
    ("my mom vs my messy room", "mom: \"how can you find anything\nin this mess?\"\nme: i know exactly\nwhere everything is.\nmom cleans my room.\ni can't find anything\nfor a month 😭"),
    ("the photo where i blink", "group photo:\n12 people.\neveryone looks perfect.\nme:\neyes closed,\nmouth open,\nmid-sneeze.\nthis one's going on the wall 😭"),
    ("checking the oven 5 times", "left the house.\nwas the oven off?\nwent back.\nit was off.\nleft again.\nwas the door locked?\nwent back 🙂"),
    ("ordering the same food every time", "food app:\n200 restaurants.\nscrolled for 45 minutes.\nordered from\nthe same place\nas the last 30 times 🙂"),
    ("me writing an important email", "writing an important email:\n\"hi!\" too happy.\n\"hello.\" too cold.\n\"hey there!\" too weird.\n40 minutes later\nstill on the first word 😭"),
    ("autumn me", "first cold day of autumn:\nbuys a pumpkin candle,\nwears a big sweater,\nmakes hot chocolate.\nit's 19 degrees outside 🙂"),
    ("me at 25 vs me at 15", "15-year-old me:\n\"at 25 i'll have\na house, a car\nand my life figured out.\"\n25-year-old me:\nexcited because\ni bought a new sponge 🙂"),
]

TITLES = [t for t, _ in _S]
_TEXTS = [x for _, x in _S]


def _assign() -> list:
    """Реф (музыка и длина) по объёму текста ≈ 23 знака в секунду; среди подходящих — наименее использованный."""
    uses = {k: 0 for k in _DUR}
    out = []
    for t in _TEXTS:
        need = len(t) / 23
        ok = [k for k, d in _DUR.items() if need <= d <= need + 1.7] or ["tt_sofiia"]
        ref = min(ok, key=lambda k: (uses[k], _DUR[k]))
        uses[ref] += 1
        out.append((ref, t))
    return out


EN = _assign()
