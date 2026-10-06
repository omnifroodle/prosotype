# Recording for a voice profile

Script version 0.1, draft, 2026-10-06. © 2026 Matt Overstreet, licensed under [CC BY 4.0](../LICENSE-CC-BY-4.0.txt). Part of the [voice profile specification](../VOICE-PROFILE.md) (§7).

This script gives a voice profile what it needs: every English sound several times, enough stressed and unstressed "p", "t" and "k" to measure aspiration, the hissing sounds, r-coloured vowels and diphthongs, and a range of deliveries. It also elicits breaths, phrase endings and phrasing, so we can decide how ProsoType should encode them. It takes about 4–5 minutes to read through, plus a minute of free speech. `prototype/script_coverage.py` checks the coverage.

## Before you record

- **Format:** WAV (uncompressed), 44.1 or 48 kHz, 16- or 24-bit, mono. Avoid voice-memo formats (AAC, M4A, MP3): compression blurs exactly the details a profile measures.
- **Processing off:** turn off noise suppression, "voice isolation", automatic gain and echo cancellation if your recorder has them. They reshape the voice.
- **Room:** quiet and soft (curtains, a sofa, clothes in a cupboard help). No fans, fridges or traffic if you can avoid them.
- **Microphone:** 20–30 cm from your mouth, slightly to one side so "p" and "b" do not thump into it. Keep the distance the same throughout.
- **Level:** your loudest words should peak around −12 to −6 dBFS, never clipping. Record five seconds of silence first, so the noise can be measured.
- **Note** your device and room; they go in the profile's `conditions`.
- **Files:** one per part: `part1.wav` … `part4.wav`.

## Reading

Read naturally, as if talking to someone across a table, not as a performance. Do not over-pronounce. If you stumble, pause and repeat the sentence. Take breaths where you normally would, and do not hide them.

### Part 1: sounds (about 2 minutes)

Read each sentence once, with a short pause between sentences.

```script
Peter took a cab to the park and paid the driver ten dollars.
Kate keeps her cats in a cottage by the coast.
Two tired teachers talked about the test at the top of the tower.
Pam put a pen and a pair of keys in the pocket of her coat.
Today the police will connect the computer to the cable together.
Perhaps the happy puppy wants a paper cup of coconut milk.
She measured the beige garage with unusual precision.
Usually, the casual treasure hunters watch television at their leisure.
The boy's choice of noisy toys annoyed his voice teacher.
Both of them thanked the author for three thoughtful theories.
Then the mother said that they should gather their other clothes.
Look, the good cook could put a wooden hook on the foot of the bed.
Judge Jenny enjoyed a large orange juice in the jungle.
Her sister bought a bottle of water and a button for her mother's sweater.
How about going out to the south mountain now?
Yesterday a young musician sang a beautiful song for you.
We wanted the white whale to swim away with us.
Hungry hikers hurried home through heavy hail.
Sue saw six small seals sitting by the sea.
Zoe was busy with zebras at the zoo, so she was always dizzy.
Fred's father found five very valuable violins.
Little lambs leap along the hill while lilies fill the field.
Rachel rarely writes; her brother reads the rest.
Many men and women meet near the mill in the morning.
Shelly should share her fresh fish with the shy chef.
The third birthday party was worth every word, Herbert heard.
```

### Part 2: deliveries (about 60 seconds)

**A. One sentence, five ways.** Say it as each description says, as you really would.

```script
You're going to the party tonight.
You're going to the party tonight?
You're going to the party tonight!
You're going to the party tonight.
You're going to the party tonight.
```

1. A plain statement of fact. 2. A surprised question. 3. Excited for them. 4. Sarcastic: you don't believe it. 5. Tired and bored; let the end trail off.

**B. Moving emphasis.** Stress the word in capitals; say the rest normally.

```script
I never said she took my bike.
I never said she took my bike.
I never said she took my bike.
I never said she took my bike.
I never said she took my bike.
I never said she took my bike.
I never said she took my bike.
```

I · NEVER · SAID · SHE · TOOK · MY · BIKE: one word per line, in that order.

**C. Phrasing.** The commas change the meaning. Show the grouping with your voice; you do not have to pause.

```script
Let's eat, Grandpa.
Let's eat Grandpa.
The teacher said the student was late.
The teacher, said the student, was late.
We need apples, bread, cheese, and milk.
Do you want tea or coffee?
Do you want tea, or coffee?
```

For the two tea lines: the first asks whether they want anything at all; the second asks which one.

**D. Endings.** Let your voice trail off naturally at the end of each.

```script
Well, I suppose that's the end of it.
Maybe we'll try again some other time.
```

### Part 3: a passage (about 45 seconds)

Read it as a story, breathing where it feels natural.

```script
The morning the old ferry stopped running, half the village came down to the harbor to watch it leave for the last time. Nobody said much. Mrs. Parker brought a thermos of tea, the children threw bread to the gulls, and the captain, who had made the crossing twice a day for thirty-one years, stood on the deck with his cap in his hands. When the engine finally started, a cheer went up that surprised everyone, including, I think, the captain himself. Then the boat turned slowly toward the open water, and we watched until it was just a small gray shape against the morning light.
```

### Part 4: free speech (30–60 seconds)

No script. Talk about something you did last weekend, or explain how you make a meal you like. Pauses, "um"s and false starts are fine; that is the point.

## Making the profile

Export the scripted parts as text, then build the profile with the forced aligner using the known words (part 4 has no text, so it uses speech recognition):

```bash
cd prototype
uv run script_coverage.py --export ../profiles/private/script
uv run voiceprofile.py build part1.wav part2.wav part3.wav part4.wav --id me --aligner mfa \
  --text ../profiles/private/script/part1.txt ../profiles/private/script/part2.txt ../profiles/private/script/part3.txt - \
  --device "your microphone" --environment "your room"
```

The profile is written to `profiles/private/me.json`. It is personal: keep it there (VOICE-PROFILE.md §6).

## Coverage

`uv run script_coverage.py` reports how often each sound occurs in a careful reading of the scripted parts, by the pronouncing dictionary, and checks it against these targets:

- every General American sound at least 5 times
- at least 20 "p", "t", "k" before a stressed vowel, at least 6 of each
- at least 10 before an unstressed vowel
- at least 8 of each hissing sound ("s", "z", "sh", "f", "th" in "thin", "th" in "then"), and 5 of "zh" (as in "measure")
- at least 8 r-coloured vowels and 8 "r"s
