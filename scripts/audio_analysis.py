from pydub import AudioSegment
import numpy as np

class AudioAnalyzer:
    def __init__(self, filepath, num_bars=50):
        self.audio = AudioSegment.from_file(filepath)
        self.num_bars = num_bars
        self.samples = np.array(self.audio.get_array_of_samples())

        # Mono or stereo?
        if self.audio.channels == 2:
            self.samples = self.samples.reshape((-1, 2))
            self.samples = self.samples.mean(axis=1)  # convert to mono

        self.sample_rate = self.audio.frame_rate
        self.duration = len(self.audio) / 1000.0  # duration in seconds

        # Normalize samples to [-1,1]
        self.samples = self.samples / np.max(np.abs(self.samples))

        # Precompute chunk size for bars
        self.chunk_size = len(self.samples) // self.num_bars

    def get_amplitudes(self, current_time):
        """
        Given current playback time in seconds, returns a list of amplitudes (0 to 1)
        for each bar of the waveform visualizer.
        """
        start_sample = int(current_time * self.sample_rate)
        amplitudes = []

        # Avoid overflow
        if start_sample + self.chunk_size * self.num_bars > len(self.samples):
            # Loop back to start or clip
            start_sample = 0

        for i in range(self.num_bars):
            chunk = self.samples[start_sample + i * self.chunk_size : start_sample + (i+1) * self.chunk_size]
            amp = np.abs(chunk).mean()
            amplitudes.append(amp)

        return amplitudes
