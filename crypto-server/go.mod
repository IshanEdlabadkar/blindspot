module github.com/IshanEdlabadkar/blindspot/crypto-server

go 1.22

require (
	github.com/ahenzinger/underhood v0.0.0-20230922182337-f053a81c6385
	github.com/henrycg/simplepir v0.0.0-20230920020624-026ee7bd6783
)

replace github.com/henrycg/simplepir => ../third_party/simplepir

replace github.com/ahenzinger/underhood => ../third_party/underhood
