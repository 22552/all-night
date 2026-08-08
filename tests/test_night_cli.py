import unittest

from night_cli import Invite, build_parser


class InviteTests(unittest.TestCase):
    def test_round_trip(self):
        original = Invite("room-id", "127.0.0.1", 12345, "secret-token")
        self.assertEqual(Invite.decode(original.encode()), original)

    def test_tampered_invite_is_rejected(self):
        invite = Invite("room-id", "127.0.0.1", 12345, "secret-token").encode()
        with self.assertRaises(ValueError):
            Invite.decode(invite[:-1] + ("A" if invite[-1] != "A" else "B"))

    def test_parser_shape(self):
        args = build_parser().parse_args(["room", "join", "invite", "--name", "alice"])
        self.assertEqual(args.room_command, "join")
        self.assertEqual(args.name, "alice")


if __name__ == "__main__":
    unittest.main()
