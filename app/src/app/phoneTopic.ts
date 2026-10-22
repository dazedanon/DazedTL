// The ntfy topic a phone subscribes to for DazedTL's notifications, and the
// link that subscribes the Android app to it.

/**
 * Everyday words of up to six letters, spelled the same in US and UK English
 * and with no slang meaning, so a topic reads well and survives a phone
 * keyboard that autocorrects made-up words.
 */
export const topicWords = `
acorn agile airy alder alert almond alpine amber anchor ant anthem ape apple
arcade arrow aspen atlas atom attic auburn aurora azure bacon badge badger bag
bagel bakery ballad ballet bamboo banjo banner barrel basil basket bat bazaar
beach beacon bean bear bee beech beetle beige bell bench berry bike birch
bison black blaze bloom blue boat bold book boot bottle bowl box branch brave
bread breeze breezy brick bridge bright brisk bronze brook broom broth brown
brush bucket buckle bugle busy butter button cabin cable cactus cafe cake calm
camel camera candle candy canoe canvas canyon cap card carpet carrot cart
cashew castle cat cave cedar celery cello cereal chair chalk chapel cheery
cheese chess chilly choir chord chorus cider cinema circus clam clever cliff
clock cloud clover coast coat cobalt cocoa coin colt comb comet condor cool
copper coral corn cosmic cosmos cove cow coyote crab cradle crafty crane
crater crayon creek crepe crisp crow cub cumin cup curry cyan cymbal daisy
dandy dapper daring dawn deer delta desert desk dew dial diner dingo dog door
dough dove dream dreamy drum duck duet dune dusk dusty eager eagle early earth
easel easy echo eel egret elk elm ember emu epic eraser fable fair falcon fan
fancy fast fawn fence fern ferret field fig finch fine fir fish flag flame
flour flower fluffy flute foal fog folder fondue forest fork fox frame fresh
frog frost frosty fudge fuzzy galaxy galley garden garlic gate gear gecko
gelato gem gentle geyser giant gibbon ginger glad glade glass glen globe glove
glow goat goblet gold golden gong goose gopher grand grape grass grassy gravy
green grove guava guitar gull hammer happy hardy hare harp hat hawk hazel
hearty heath helmet hen herb heron hill hippo honest honey hook horse hound
house humble ibis iguana impala indigo iris island ivory ivy jackal jade jam
jar jay jazz jazzy jelly jewel jigsaw jolly joyful jungle kale kayak keen
kettle key kind kite koala ladder ladle lagoon lake lamb lamp larch lark laser
laurel leaf leek legend lemon lemur lens lentil letter lever light lilac lily
lime lion lively lizard llama lock locket lotus lucky lunar lute lynx magic
magnet magpie mallet mango map maple marble market marsh mauve meadow medal
mellow melody merry mesa meteor mighty mink mint mirror mist misty mitten
mocha mole moon moose mosaic moss mossy moth mouse mug mule museum music nacho
napkin navy neat nebula nectar needle nest net newt nifty nimble noble noodle
nougat nova oak oar oasis oat oboe ocean ocelot olive onion opal opera orange
orbit orca orchid osprey otter oven owl oyster paddle page paint palace palm
pan panda papaya paper parade parcel parrot pasta pastry peanut pear pearl
pebble pecan pedal pen pencil pepper pesto petal photon piano picnic pie
pigeon pillar pillow pin pine pink pipe pixel pizza planet plank plate plaza
plucky pocket poem polar polite pollen pond pony poplar poppy pot potato prism
proton proud puffin pulley purple puzzle quail quartz quasar quest quiche
quick quiet quill quilt radio radish rain raisin rake ramen rapid rapids rare
raven ready red reef rhyme ribbon rice riddle ridge ring river robin robot
rock rocket rodeo rope rose rosy royal ruby rudder rug ruler rust rustic
saddle safari sage sail salad salmon salsa sand sandal sandy scarf school
scone scroll sea seal sesame shadow shark sheep shelf shell shiny ship shoe
shore shovel shrimp sierra silent silky silver simple skate sketch skunk sky
sled sleek slide sloth smart smooth snail snake snow snowy sock sofa soft
solid solo sonata sonnet sorbet soup spark spice spider sponge spool spoon
spring spruce squash squid stamp star statue steady stone stork storm story
stove stream string studio sturdy sugar summit sun sundae sunny sunset super
sushi swan sweet swift syrup table tablet taffy tahini tan tango tapir tavern
tea teacup teal teapot temple tempo tent thread thyme ticket tide tidy tiger
tile timber timer tiny toad toast toffee tofu tomato torch toucan towel tower
train tray tree trio tripod trivia trophy trout trowel trunk tuba tulip tuna
tundra tunic tunnel turkey turnip turtle umber upbeat utopia valley vase
velvet viola violet violin viper vivid vole vortex voyage waffle wagon wallet
walnut walrus waltz warm wasabi wave weasel whale wheat wheel whisk white wild
willow wind window windy wise wish witty wolf wombat wreath wren yak yam yarn
yeast yellow young zebra zenith zesty zipper zippy
`
  .trim()
  .split(/\s+/);

/** A word picked evenly from the list, with no bias toward its start. */
function randomWord() {
  const limit = Math.floor(2 ** 32 / topicWords.length) * topicWords.length;
  const value = new Uint32Array(1);
  do crypto.getRandomValues(value);
  while (value[0] >= limit);
  return topicWords[value[0] % topicWords.length];
}

/**
 * A topic such as `dazed-maple-otter-river`: ntfy shows a topic's messages to
 * whoever subscribes to it, so three of these words keep them the user's
 * while staying easy to type.
 */
export function newTopic() {
  return ["dazed", randomWord(), randomWord(), randomWord()].join("-");
}

/** Opens the ntfy Android app on the topic and subscribes it, as "DazedTL". */
export const subscribeLink = (topic: string) =>
  `ntfy://ntfy.sh/${topic}?display=DazedTL`;
