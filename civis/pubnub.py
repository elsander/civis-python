from civis import APIClient
from civis.base import CivisJobFailure, CivisAsyncResultBase, FAILED, DONE

try:
    from pubnub.pubnub import PubNub
    from pubnub.pnconfiguration import PNConfiguration
    from pubnub.callbacks import SubscribeCallback
    has_pubnub = True
except ImportError:
    has_pubnub = False


if has_pubnub:
    class JobCompleteListener(SubscribeCallback):
        def __init__(self, job_id, run_id, callback_function):
            self.job_id = job_id
            self.run_id = run_id
            self.callback_function = callback_function

        def message(self, pubnub, message):
            try:
                result = message.message
                if result['object']['id'] == self.job_id \
                        and result['run']['id'] == self.run_id \
                        and result['run']['state'] in DONE:
                    self.callback_function()
            except KeyError:
                pass

        def status(self, pubnub, status):
            pass

        def presence(self, pubnub, presence):
            pass


class SubscribableResult(CivisAsyncResultBase):
    """
    A class for tracking subscribable results.

    This class will subscribe to a Pubnub channel upon creation, and listen
    for messages that indicate a job completion.

    Parameters
    ----------
    poller : func
        A function which returns an object that has a ``state`` attribute.
    poller_args : tuple
        The arguments with which to call the poller function.
    api_key : str, optional
        Your Civis API key. If not given, the :envvar:`CIVIS_API_KEY`
        environment variable will be used.
    """
    def __init__(self, poller, poller_args, api_key=None):
        super().__init__()

        self.poller = poller
        self.poller_args = poller_args
        self.api_key = api_key
        self._pubnub = self._subscribe()

    def _subscribe(self):
        pnconfig, channels = self._pubnub_config()
        listener = JobCompleteListener(self.poller_args[0],
                                       self.poller_args[1],
                                       self._check_api_result)
        pubnub = PubNub(pnconfig)
        pubnub.add_listener(listener)
        pubnub.subscribe().channels(channels).execute()
        return pubnub

    def _pubnub_config(self):
        client = APIClient(api_key=self.api_key, resources='all')
        channel_config = client.channels.list()
        channels = [channel['name'] for channel in channel_config['channels']]
        pnconfig = PNConfiguration()
        pnconfig.subscribe_key = channel_config['subscribe_key']
        pnconfig.cipher_key = channel_config['cipher_key']
        pnconfig.auth_key = channel_config['auth_key']
        pnconfig.ssl = True
        pnconfig.reconnect_policy = True
        return pnconfig, channels

    def _check_api_result(self, result=None):
        with self._condition:
            if result is None:
                result = self.poller(*self.poller_args)
            if result.state in FAILED:
                if self._pubnub:
                    self._pubnub.unsubscribe_all()
                try:
                    err_msg = str(result['error'])
                except:
                    err_msg = str(result)
                self.set_exception(CivisJobFailure(err_msg,
                                                   result))
                self._result = result
            elif result.state in DONE:
                if self._pubnub:
                    self._pubnub.unsubscribe_all()
                self.set_result(result)
