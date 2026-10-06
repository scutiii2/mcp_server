"""Word list for passphrases: common, short, unambiguous lowercase English
words. Entropy per word is log2(len(WORDS)); duplicates are dropped at
import so a slip here can never shrink the effective list silently."""

from __future__ import annotations

_RAW = """
able acid acorn actor adapt adult agent agree ahead alarm album alert alien alley allow alloy alone alpha
alter amber ample angel anger angle ankle apple apron arena argue arise armor array arrow aside asset
atlas atom attic audio avoid awake award aware bacon badge bagel baker balsa banjo barn basil basin batch
beach beard beast begin bench berry bike bingo birch bison blade blank blast blaze blend bless blink bliss
block bloom blues blunt board boast boat bonus boost booth bored bound brain brake brand brave bread break
brick bride brief bring brisk broad broom brown brush bucket buddy build bulb bunch burst cabin cable cacti
cadet camel canal candy canoe canyon cargo carol carry carve cabin cedar chain chair chalk champ charm chart
chase cheap check cheek cheer chess chest chief child chill chime chip choir chord chrome cider cigar cinch
circle civic claim clamp clash class clay clean clear clerk click cliff climb cloak clock close cloth cloud
clove clown coach coast cobra cocoa coin comet comic coral cork couch cough count court cover crab craft
crane crash crate crazy cream creek creep crest crisp crown crumb crush crust cube cup curb curly curve cycle
daily daisy dance dandy dash dawn deal debut decay deck decor deep delta demo denim depth desk detail dial
diary diesel diner dingo dish ditch dive dizzy dock dodge doll donor donut dove dozen draft drain drama drape
dream dress drift drill drink drive drone drum dry duck dusk dust duty eager eagle early earth ease easel
echo edge eight elbow elder elite elm ember emerge empty enjoy enter entry envoy equal erase error essay
event every exact exam exit extra fable face fact fade fairy faith false fame fancy farm fast fault
feast fence fern ferry fetch fever fiber field fiery fifth fifty fight film final finch find fire firm first
fish fist fixed fizz flag flair flame flap flash flask fleet flesh flint float flock flood floor flour flow
fluid flute foam focus fog foil folk food forge fork form fort forum fossil found fox frame frank fresh
friar frog front frost fruit fudge fuel full fun fungi funny fuzzy gadget gain gala galaxy game gap garden
garlic gate gauge gaze gear gecko gem genie gentle ghost giant gift ginger giraffe girl glad glance glass
gleam glide glint globe gloom glory glove glow glue goat gold golf good goose gorge grace grade grain grand
grape graph grasp grass grave gravy great green greet grid grill grin grip groom group grove growl grown
guard guess guest guide guild gull gust gym habit hairy half hall halo hammer hand handy happy harbor hard
hare harp haste hatch haven hawk hazel heart heat heavy hedge heel hello helm help hen herb herd hero hike
hill hinge hint hippo hobby hockey hold holly home honey honor hood hoof hook hope horn horse host hotel
hound hour house hover howl hub huge human humor hunt hurry hush hut hymn icon idea igloo image inch index
inlet inner input iron isle issue ivory ivy jacket jade jaguar jam jar jazz jeans jelly jewel jig jingle
job join joke jolly joy judge juice jumbo jump jungle junior junk jury kayak keen keep kettle key kick
kid kind king kiosk kite kitten kiwi knee knife knit knob knock knot koala label lace ladder lady lake lamb
lamp land lane lapel large laser lasso latch laugh lava lawn layer lazy leaf learn lease least leave ledge
left lemon lend lens lentil level lever light lilac lily limb lime limit linen link lion lip list liter
little liver lizard llama load loaf lobby local lock lodge loft logic long loom loop loose lotus loud love
low loyal lucky lumber lunar lunch lush lute lynx magic magma maize major maker mango maple marble march
mark marsh mask match maze meadow meal medal media melon memo mend menu mercy merge merit merry mesh metal
meter micro midst might mild mile milk mill mimic mind mine mint minor minus mirror mist mitten mix moat
mocha model modem moist molar moment money monk month moon moose moral moss motel moth motor motto mound
mount mouse mouth move movie mud mug mule mural music mute myth nacho nail name nap navy neat neck needle
nerve nest net never new nickel night nimble noble nod noise noodle north nose note novel nudge nurse nut
oak oasis oat ocean octave odd off often oil okay old olive omega onion onyx opal open opera optic orbit
orchid order organ otter ounce outer oval oven owl owner oxen oyster ozone pace pack paddle page pail paint
pair palm panda panel panic pansy paper park parrot party pasta paste patch path patrol pause paw peace
peach peak pear pearl pecan pedal peel pelican pen penny pepper perch petal phase phone photo piano pick
picnic piece pier pig pilot pinch pine pink pioneer pipe pitch pixel pizza place plain plan plane plank
plant plaza plot plow plum plume plush poem poet point polar pole polo pond pony pool poppy porch port pose
post pouch pound power prank press price pride prime print prism prize proof proud pulse puma pump punch
pupil puppy purple purse puzzle quail quake quartz queen query quest quick quiet quill quilt quit quiz
quota rabbit raccoon race radar radio raft rail rain raise rally ranch range rapid raven razor reach react
ready realm rebel recipe reef relax relay remix renew reply rescue rest rhino rhyme rib rice rich ride ridge
rifle right rigid ring rinse ripe rise risk ritual river road roast robin robot rock rocket rogue roll
roof rook room root rope rose rough round route rover royal ruby rug ruin rule rumor run rural rush
rust sable sack sadly safe sage sail salad salmon salon salt sand sandy satin sauce sauna savor scale scarf
scene scent school scone scoop scout scrap screen script sea seal seat second seed seesaw sense serve set
seven shade shadow shaft shake shape share shark sharp shawl sheep sheet shelf shell shine ship shirt shock
shoe shore short shout show shrub shy sick side siege sight sigma silk silly silver simple sing siren sit
six size skate sketch ski skill skin skirt skull sky slate sled sleek sleep slice slide slim slope slow
small smart smell smile smoke smooth snack snail snake snap sneak snow soap sock sofa soft soil solar solid
solo solve sonic sound soup south space spade spare spark speak speed spell spice spike spin spiral spoon
sport spot spray spring spruce spy square squid stable staff stage stair stamp stand star start state steam
steel stem step stew stick stiff still sting stir stock stone stood stool stop store storm story stove
straw stream street strike strip strong studio study stuff style sugar suit sum summer sun super supper
surf surge swamp swan swap sway sweet swift swim swing sword syrup table tackle tail talent talk tall tame
tango tank tape target tart task taste taxi teach team tease teeth tempo tennis tent term test text thank
theme thick thief thing think third thorn three throw thumb thunder ticket tide tidy tiger tile till timber
time tin tiny tip tire title toast today toe token tomato tone tonic tool tooth top topic torch total touch
tough tour towel tower town toy trace track trade trail train trap tray tread tree trend trial tribe trick
trio trip troop trout truck true trunk trust truth tub tulip tuna tune tunnel turkey turn turtle tutor twig
twin twist type ultra uncle under union unit unity upper urban urge usage use usual utter vague valid valley
value valve vapor vault velvet venue verse vest veto video view villa vine violet viper virus visit visor
vista vital vivid vocal voice volt vote vowel wafer wage wagon waist wait wake walk wall walnut waltz wand
want warm warn wash wasp watch water wave wax way weak wealth weave web wedge week weigh weird well whale
wheat wheel whip whisk white whole wick wide widow width wild willow wind wine wing winter wire wise wish
witch wolf woman wonder wood wool word work world worm worry worth wrap wreck wren wrist write yacht yard
yarn year yeast yell yellow yield yoga young youth yucca zebra zen zero zest zinc zone zoo zoom
"""

WORDS: tuple[str, ...] = tuple(dict.fromkeys(_RAW.split()))
