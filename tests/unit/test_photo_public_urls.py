from scripts.migrate_photo_public_urls import NEW_BASE, OLD_BASE, rewrite_photo_url


def test_rewrite_photo_url_moves_private_api_url_to_public_domain() -> None:
    assert rewrite_photo_url(f"{OLD_BASE}/users/account/photo.jpg") == (
        f"{NEW_BASE}/users/account/photo.jpg"
    )


def test_rewrite_photo_url_preserves_public_and_missing_urls() -> None:
    assert rewrite_photo_url(f"{NEW_BASE}/users/account/photo.jpg") == (
        f"{NEW_BASE}/users/account/photo.jpg"
    )
    assert rewrite_photo_url(None) is None
