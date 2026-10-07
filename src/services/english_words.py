# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""常用英文词表（口音纠错的硬闸门）。

为什么必须内嵌
--------------
没有词级纠错就是瞎猜。实测打地鼠式补词表：
    补了 let/should -> 下一轮 "fire in the hole" -> "fire in the heal"
    再补 hole     -> 下一轮又会有别的
只要没有"这个词是不是英语"的判据，误伤就无法收敛。

用户听到一句被改坏的句子，比听到一句原样英文糟糕得多
（"nice shot my friend" -> "ns shoot my friend" 这种绝不能出现），
所以宁可不纠，也不能改错。

这份表覆盖日常口语 95% 以上的词，只有不在表里的词
才允许被音形匹配改写。游戏里的特殊词（heaven/spike/defuse…）
本来也不在英语常用词里，因此不会被误保护。

数据：按词频整理的常用英语词表（动词/名词/形容词/副词/代词/连词）。
"""
from __future__ import annotations

COMMON_EN = set("""
a about above accept across act add afraid after again against age ago
agree air all allow almost alone along already also although always am
among an and angry animal another answer any anyone anything appear are
around arrive as ask at attack attempt away back bad bag ball bank bar
base basic be bear beat beautiful because become bed been before begin
behind believe below best better between big bill bird bit black block
blood blow blue board boat body bomb book both bottom box boy break bring
brother brown build burn bus business busy but buy by call calm can car
card care carry case catch cause center certain change charge cheap check
child choose church city claim clean clear climb clock close clothes cloud
club cold collect college color come common company compare complete
computer concern condition consider contain continue control cook cool copy
corner correct cost could count country course cover create cross cry cut
dance danger dark data date daughter day dead deal dear death decide deep
defend degree depend describe design desk detail develop die difference
different difficult dinner direct discuss distance doctor dog door down
draw dream dress drink drive drop drug during each early earth east easy
eat edge effect eight either electric else empty end enemy energy enjoy
enough enter entire environment error especially even evening event ever
every everyone everything evidence exact example except expect experience
explain eye face fact fail fair fall family famous far farm fast father
fear feel fight figure fill film final finally find fine finger finish
fire firm first fish fit five fix flag flat floor flow flower fly focus
follow food foot for force forget form four free friend front full fun
fund future game garden gas general girl give glass go goal good got
government grade grand great green ground group grow guess gun guy
hair half hand hang happen happy hard has hat have he head health hear
heart heat heavy help her here herself high him himself his history hit
hold hole home hope horse hot hotel hour house how however huge human
hundred hunt hurry hurt husband i ice idea if image imagine important in
include increase indeed information inside instead interest into introduce
is issue it item its itself job join just keep key kid kill kind king
kitchen knee know land language large last late later laugh law lay lead
learn least leave left leg length less let letter level lie life light
like likely line list listen little live local long look lose lot love
low lunch machine main make man many map mark market marriage master match
matter maybe me mean measure meat meet member memory mention message metal
method middle might mile military milk million mind mine minute miss
mission model modern moment money month more morning most mother move
movie much music must my myself name nation nature near nearly necessary
need neighbor never new news next nice night nine no none nor north not
note nothing notice now number occur off offer office often oil old on
once one only open operation opinion opportunity option or order other our
out outside over own page pain paint pair paper parent park part party pass
past path pay peace people per perfect perhaps period person phone
physical pick picture piece place plan plant play player please point
police policy political poor popular population position possible power
practice prepare present president press pressure pretty prevent price
private probably problem process produce product program project property
protect prove provide public pull purpose push put quality question quick
quite race radio raise range rate rather reach read ready real reality
realize really reason receive recent recognize record red reduce reflect
region relate relationship religious remain remember remove report represent
republic require research resource respond response responsibility rest
result return reveal rich right rise risk road rock role room rule run
safe same save say scene school science score sea season seat second
section security see seek seem sell send senior sense sentence series
serious serve service set seven several sex shake share she shoot short
shot should shoulder show side sign significant similar simple simply since
sing single sister sit site situation six size skill skin sky small smile
social society soldier some somebody someone something sometimes son song
soon sort sound source south southern space speak special specific speech
spend sport spring staff stage stand standard star start state statement
station stay step still stock stop store story strategy street strong
structure student study stuff style subject success such sudden suffer
suggest summer support sure surface system table take talk task tax teach
teacher team tear technology television tell ten tend term test than thank
that the their them themselves then theory there these they thing think
third this those though thought thousand threat three through throughout
throw thus time today together tonight too top total tough toward town
trade traditional training travel treat treatment tree trial trip trouble
true truth try turn two type under understand unit until up upon us use
usually value various very view village violence visit voice vote wait
walk wall want war watch water way we weapon wear week weight well west
western what whatever when where whether which while white who whole whom
whose why wide wife will win wind window wish with within without woman
wonder word work worker world worry would write writer wrong yard yeah
year yes yet you young your yourself
""".split())