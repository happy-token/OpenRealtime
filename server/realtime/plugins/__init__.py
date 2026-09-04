"""Typed audio Processor, Analyzer, and Sink plugin execution."""

from server.realtime.plugins.context import CapabilityContext, capability_context_for
from server.realtime.plugins.graph import (
    AudioAnalysisProduced,
    AudioPluginContractError,
    AudioPluginDegraded,
    AudioPluginEvent,
    AudioPluginFailed,
    AudioPluginFailure,
    AudioPluginGap,
    AudioPluginGraph,
    AudioPluginLatencyExceeded,
)
from server.realtime.plugins.interfaces import (
    AudioAnalysisEvidence,
    AudioAnalyzerBinding,
    AudioAnalyzerSession,
    AudioProcessorBinding,
    AudioProcessorSession,
    AudioSinkBinding,
    AudioSinkSession,
    SpeakerDecision,
    SpeakerEvidence,
)

__all__ = [
    "AudioAnalysisEvidence",
    "AudioAnalysisProduced",
    "AudioAnalyzerBinding",
    "AudioAnalyzerSession",
    "AudioPluginContractError",
    "AudioPluginDegraded",
    "AudioPluginEvent",
    "AudioPluginFailed",
    "AudioPluginFailure",
    "AudioPluginGap",
    "AudioPluginGraph",
    "AudioPluginLatencyExceeded",
    "AudioProcessorBinding",
    "AudioProcessorSession",
    "AudioSinkBinding",
    "AudioSinkSession",
    "CapabilityContext",
    "SpeakerDecision",
    "SpeakerEvidence",
    "capability_context_for",
]
