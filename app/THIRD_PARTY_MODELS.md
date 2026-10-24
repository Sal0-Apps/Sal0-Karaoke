# Additional alignment model

The optional CPU alignment stage downloads the MMS forced-alignment checkpoint
published by Meta and exposed through TorchAudio 2.6 `MMS_FA`. Its weights have
their own **CC-BY-NC 4.0** license, independent of this repository's source-code
license. The checkpoint is downloaded on first use and is not bundled in this
repository or its image. Model reference and attribution:

- Pratap et al., *Scaling Speech Technology to 1,000+ Languages* (Meta).
- https://docs.pytorch.org/audio/2.6.0/generated/torchaudio.pipelines.MMS_FA.html
- https://github.com/facebookresearch/fairseq/tree/main/examples/mms#license

The CPU regression script downloads *Cortez — Feel (Stripped)*, identified as
**CC BY** in the JamendoLyrics dataset metadata, with its independently annotated
word times. The recording/lyrics are used only during validation, not shipped as
application assets. Dataset snapshot:

https://github.com/f90/jamendolyrics/tree/f093b7a74e034deac21eb5ea3fc40769b29c35b0

The controlled test offsets the input word clocks by 400 ms, replaces one word
and appends three words in digital silence. Reported timing differences measure
that alignment test; they are not a general ASR transcription benchmark.

The CPU test also compares a single recorded phrase with a real repetition made
from the same sung audio. Full-sequence CTC likelihood must reject duplicated
text for one occurrence and preserve both actually sung occurrences.

The complete-guide regression removes an entire annotated line and individual
words, then repeats the recorded phrase after seven seconds of digital silence.
It uses the installed Whisper model for known-text alignment and MMS to refine
clocks while preserving confirmed text. The complete-guide test has 43 words;
its timing error is measured against the same independent annotations.

For confirmed complete guides, nonblank phone posterior mass and vocal energy
also provide supporting activity near sung verses. This prevents speech-VAD
misses on sustained vowels from generating instrumental notices; it does not
create word text or word timestamps.
