from steemapi.steemclient import SteemNodeRPC
from steembase import PrivateKey, PublicKey, Address
import steembase.transactions as transactions
from piston.utils import (
    resolveIdentifier,
    constructIdentifier,
    derivePermlink,
)
from piston.wallet import Wallet
from piston.configuration import Configuration

#: Global variables
rpc = None
nobroad = False

#: Configuration from local user settings
config = Configuration()

#: Default settings
if "node" not in config or not config["node"]:
    config["node"] = "wss://steemit.com/ws"


def executeOp(op, wif=None):
    """ Execute an operation by signing it with the `wif` key and
        broadcasting it to the Steem network

        :param Object op: The operation to be signed and broadcasts as
                          provided by the `transactions` class.
        :param string wif: The wif key to use for signing a transaction

        **TODO**: The full node could, given the operations, give us a
        set of public keys that are required for signing, then the
        public keys could used to identify the wif-keys from the wallet.

    """
    if not wif:
        print("Missing required key")
        return

    ops    = [transactions.Operation(op)]
    expiration = transactions.formatTimeFromNow(30)
    ref_block_num, ref_block_prefix = transactions.getBlockParams(rpc)
    tx     = transactions.Signed_Transaction(
        ref_block_num=ref_block_num,
        ref_block_prefix=ref_block_prefix,
        expiration=expiration,
        operations=ops
    )
    tx = tx.sign([wif])
    from pprint import pprint
    pprint(transactions.JsonObj(tx))

    if not nobroad:
        if isinstance(tx, transactions.Signed_Transaction):
            tx = transactions.JsonObj(tx)
        reply = rpc.broadcast_transaction(tx, api="network_broadcast")
        if reply:
            print(reply)
    else:
        print("Not broadcasting anything!")
        reply = None

    return tx


def connect(node=None, rpcuser=None, rpcpassword=None, nobroadcast=False):
    """ Connect to the Steem network.

        :param str node: Node to connect to *(optional)*
        :param str rpcuser: RPC user *(optional)*
        :param str rpcpassword: RPC password *(optional)*
        :param bool nobroadcast: Do **not** broadcast a transaction!

        If no node is provided, it will connect to the node of
        SteemIT.com. It is **highly** recommended that you pick your own
        node instead. Default settings can be changed with:

        ```
        piston set node <host>
        ```

        where `<host>` starts with `ws://` or `wss://`.
    """
    global nobroad
    global rpc
    nobroad = nobroadcast
    if not node:
        if "node" in config:
            node = config["node"]
        else:
            raise ValueError("A Steem node needs to be provided!")

    if not rpcuser and "rpcuser" in config:
        rpcuser = config["rpcuser"]

    if not rpcpassword and "rpcpassword" in config:
        rpcpassword = config["rpcpassword"]

    rpc = SteemNodeRPC(node, rpcuser, rpcpassword)
    return rpc


def reply(identifier, body, title="", author="", meta=None):
    """ Reply to an existing post

        :param str identifier: Identifier of the post to reply to. Takes the
                         form `@author/permlink`
        :param str body: Body of the reply
        :param str title: Title of the reply post
        :param str author: Author of reply (optional) if not provided
                           `default_user` will be used, if present, else
                           a `ValueError` will be raised.
        :param json meta: JSON meta object that can be attached to the
                          post. (optional)
    """
    post(title, body, meta=meta, author=author, reply_identifier=identifier)


def edit(identifier, body, meta=None, replace=False):
    """ Edit an existing post

        :param str identifier: Identifier of the post to reply to. Takes the
                         form `@author/permlink`
        :param str body: Body of the reply
        :param json meta: JSON meta object that can be attached to the
                          post. (optional)
        :param bool replace: Instead of calculating a *diff*, replace
                             the post entirely (defaults to `False`)
    """
    post_author, post_permlink = resolveIdentifier(identifier)
    original_post = rpc.get_content(post_author, post_permlink)

    if replace:
        newbody = body
    else:
        import diff_match_patch
        dmp = diff_match_patch.diff_match_patch()
        patch = dmp.patch_make(original_post["body"], body)
        newbody = dmp.patch_toText(patch)

        if not newbody:
            print("No changes made! Skipping ...")
            return

    reply_identifier = constructIdentifier(
        original_post["parent_author"],
        original_post["parent_permlink"]
    )

    post(original_post["title"],
         newbody,
         reply_identifier=reply_identifier,
         author=original_post["author"],
         permlink=original_post["permlink"],
         meta=original_post["json_metadata"])


def post(title, body,
         author=None,
         permlink=None, meta="",
         reply_identifier=None, category=""):
    """ New post

        :param str title: Title of the reply post
        :param str body: Body of the reply
        :param str author: Author of reply (optional) if not provided
                           `default_user` will be used, if present, else
                           a `ValueError` will be raised.
        :param json meta: JSON meta object that can be attached to the
                          post.
        :param str reply_identifier: Identifier of the post to reply to. Takes the
                                     form `@author/permlink`
        :param str category: Allows to define a category for new posts.
                             It is highly recommended to provide a
                             category as posts end up in `spam`
                             otherwise.
    """

    if not author and config["default_author"]:
        author = config["default_author"]

    if not author:
        raise ValueError(
            "Please define an author. (Try 'piston set default_author'"
        )

    if reply_identifier and not category:
        parent_author, parent_permlink = resolveIdentifier(reply_identifier)
    elif category and not reply_identifier:
        parent_permlink = category
        parent_author = ""
    elif not category and not reply_identifier:
        parent_author = ""
        parent_permlink = ""
    else:
        raise ValueError(
            "You can't provide a category while replying to a post"
        )

    if not permlink:
        permlink = derivePermlink(title, parent_permlink)

    op = transactions.Comment(
        **{"parent_author": parent_author,
           "parent_permlink": parent_permlink,
           "author": author,
           "permlink": permlink,
           "title": title,
           "body": body,
           "json_metadata": ""}  # fixme: allow for posting of metadata
    )
    wif = Wallet(rpc).getPostingKeyForAccount(author)
    executeOp(op, wif)


def vote(identifier, weight, voter=None):
    """ Vote for a post

        :param str identifier: Identifier for the post to upvote Takes
                               the form `@author/permlink`
        :param float weight: Voting weight. Range: -100.0 - +100.0. May
                             not be 0.0
        :param str voter: Voter to use for voting. (Optional)
        
        If `voter` is not defines, the `default_voter` will be taken or
        a ValueError will be raised

        ```
        piston set default_voter <account>
        ```
    """

    STEEMIT_100_PERCENT = 10000
    STEEMIT_1_PERCENT = (STEEMIT_100_PERCENT / 100)

    if not voter:
        if "default_voter" in config:
            voter = config["default_voter"]
    if not voter:
        raise ValueError("You need to provide a voter account")

    post_author, post_permlink = resolveIdentifier(identifier)

    op = transactions.Vote(
        **{"voter": voter,
           "author": post_author,
           "permlink": post_permlink,
           "weight": int(weight * STEEMIT_1_PERCENT)}
    )
    wif = Wallet(rpc).getPostingKeyForAccount(voter)
    executeOp(op, wif)


def get_content(identifier):
    """ Get the full content of a post.

        :param str identifier: Identifier for the post to upvote Takes
                               the form `@author/permlink`
    """
    post_author, post_permlink = resolveIdentifier(identifier)
    return rpc.get_content(post_author, post_permlink)


def get_replies(author, skipown=True):
    """ Get replies for an author

        :param str author: Show replies for this author
        :param bool skipown: Do not show my own replies
    """
    state = rpc.get_state("/@%s/recent-replies" % author)
    replies = state["accounts"][author]["recent_replies"]
    discussions  = []
    for reply in replies:
        post = state["content"][reply]
        if skipown and post["author"] == author:
            continue
        discussions.append(post)
    return discussions


def get_posts(limit=10,
              sort="recent",
              category=None,
              start=None,):
    """ Get multiple posts in an array.

        :param int limit: Limit the list of posts by `limit`
        :param str sort: Sort the list by "recent" or "payout"
        :param str category: Only show posts in this category
        :param str start: Show posts after this post. Takes an
                          identifier of the form `@author/permlink`
    """
    from functools import partial
    if sort == "recent":
        if category:
            func = partial(rpc.get_discussions_in_category_by_last_update, category)
        else:
            func = rpc.get_discussions_by_last_update
    elif sort == "payout":
        if category:
            func = partial(rpc.get_discussions_in_category_by_total_pending_payout, category)
        else:
            func = rpc.get_discussions_by_total_pending_payout
    else:
        print("Invalid choice of '--sort'!")
        return

    author = ""
    permlink = ""
    if start:
        author, permlink = resolveIdentifier(start)

    return func(author, permlink, limit)


def get_categories(sort, begin="", limit=10):
    """ List categories

        :param str sort: Sort categories by "trending", "best",
                         "active", or "recent"
        :param str begin: Show categories after this
        :param int limit: Limit categories by `x`
    """
    if sort == "trending":
        func = rpc.get_trending_categories
    elif sort == "best":
        func = rpc.get_best_categories
    elif sort == "active":
        func = rpc.get_active_categories
    elif sort == "recent":
        func = rpc.get_recent_categories
    else:
        print("Invalid choice of 'sort'!")
        return

    return func(begin, limit)
