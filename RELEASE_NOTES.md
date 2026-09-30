# 9.9.3

- Reorganiza a administração do YouTube em conexão do canal, playlists por usuário, publicação manual e histórico.
- Conexão e salvamento mostram progresso, sucesso e erro junto ao controle usado.
- Cada usuário tem controles separados para permissão, playlist e publicação marcada por padrão.
- Falhas ao consultar playlists não escondem a lista de usuários nem apagam o estado do canal conectado.
- Verifica permissões no Google quando a resposta de renovação não inclui o campo scope.
- Mensagens de conexão explicam API desativada, conta sem canal e cota atingida.
- Testes de interface cobrem conexão com falha e sucesso, destino por usuário e telas mobile/desktop.
