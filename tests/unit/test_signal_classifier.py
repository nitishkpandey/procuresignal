import pytest
from procuresignal.signals.classifier import SignalClassifier, SignalType


@pytest.fixture
def classifier():
    return SignalClassifier()


def test_bankruptcy_detection(classifier):
    article = "Company ABC filed for Chapter 11 bankruptcy protection."
    signals = classifier.classify(article, "ABC Inc Files Bankruptcy")

    assert len(signals) > 0
    assert signals[0].signal_type == SignalType.BANKRUPTCY
    assert signals[0].confidence > 0.75


def test_m_and_a_detection(classifier):
    article = "Tech giant XYZ has acquired competitor 123 Corp for $5 billion."
    signals = classifier.classify(article, "XYZ Acquires 123 Corp")

    assert len(signals) > 0
    assert signals[0].signal_type == SignalType.M_AND_A


def test_tariff_detection(classifier):
    article = "Government announces new 25% tariff on imported steel."
    signals = classifier.classify(article, "New Steel Tariffs Announced")

    assert len(signals) > 0
    assert signals[0].signal_type == SignalType.TARIFF


def test_no_false_positives(classifier):
    article = "The weather is nice today and the market is down slightly."
    signals = classifier.classify(article, "Weather and Markets")

    assert len(signals) == 0
