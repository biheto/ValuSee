from app.shopping.reviews import analyze_reviews


def test_review_analysis_requires_source_bearing_evidence():
    result = analyze_reviews([{"content": "电池发热", "rating": 1, "source": ""}])

    assert result["risk_level"] == "unknown"
    assert result["sample_size"] == 0


def test_review_analysis_weights_verified_negative_reviews():
    result = analyze_reviews(
        [
            {
                "content": "续航很差而且使用时明显发热",
                "rating": 1,
                "verified_purchase": True,
                "source": "user-extension",
            },
            {
                "content": "包装完好，暂时使用正常",
                "rating": 5,
                "verified_purchase": False,
                "source": "user-extension",
            },
        ]
    )

    assert result["risk_level"] == "high"
    assert result["sample_size"] == 2
    assert result["issue_groups"][0]["name"] == "续航与发热"
    assert result["issue_groups"][0]["evidence"]
