from server.brain.status_inquiry import KeywordStatusInquiryClassifier


async def test_recognizes_builtin_status_phrase():
    classifier = KeywordStatusInquiryClassifier()

    is_status_inquiry = await classifier.is_status_inquiry(text="怎么样了", generation=1)

    assert is_status_inquiry is True


async def test_recognizes_builtin_status_phrase_case_insensitive():
    classifier = KeywordStatusInquiryClassifier()

    is_status_inquiry = await classifier.is_status_inquiry(text="Any Update on that?", generation=1)

    assert is_status_inquiry is True


async def test_unrelated_text_is_not_a_status_inquiry():
    classifier = KeywordStatusInquiryClassifier()

    is_status_inquiry = await classifier.is_status_inquiry(
        text="actually, book me a hotel instead", generation=1
    )

    assert is_status_inquiry is False


async def test_custom_phrases_are_honored():
    classifier = KeywordStatusInquiryClassifier(("进展如何",))

    assert await classifier.is_status_inquiry(text="进展如何？", generation=1) is True
    assert await classifier.is_status_inquiry(text="怎么样了", generation=1) is False
