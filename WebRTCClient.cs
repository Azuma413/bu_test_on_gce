using UnityEngine;
using Unity.WebRTC;
using System.Collections;
using UnityEngine.UI;
using System;
using System.Text;
using UnityEngine.Networking;

[Serializable]
public class WebRTCMessage
{
    public string type;
    public string sdp;
}

public class WebRTCClient : MonoBehaviour
{
    [SerializeField] private RawImage displayImage;
    private RTCPeerConnection peerConnection;
    private MediaStream receiveStream;
    private RTCDataChannel dataChannel;
    [SerializeField] private string ServerUrl = "https://34.133.108.164:8443";
    private VideoStreamTrack videoStreamTrack;

    private void Start()
    {
        StartCoroutine(SetupWebRTC());
    }

    private IEnumerator SetupWebRTC()
    {
        // Configure and initialize RTCPeerConnection with ICE servers
        var config = GetDefaultConfiguration();
        peerConnection = new RTCPeerConnection(ref config);

        // Setup event handlers
        peerConnection.OnTrack = (RTCTrackEvent e) =>
        {
            if (e.Track is MediaStreamTrack track && track.Kind == TrackKind.Video)
            {
                receiveStream = new MediaStream();
                receiveStream.AddTrack(track);
                videoStreamTrack = track as VideoStreamTrack;
                videoStreamTrack.OnVideoReceived += UpdateDisplayImage;
            }
        };

        peerConnection.OnConnectionStateChange = state =>
        {
            Debug.Log($"Connection State: {state}");
        };

        peerConnection.OnIceCandidate = candidate =>
        {
            Debug.Log($"ICE Candidate: {candidate}");
        };

        // Create and send offer
        var op = peerConnection.CreateOffer();
        yield return op;

        if (op.IsError)
        {
            Debug.LogError($"Create Offer Error: {op.Error.message}");
            yield break;
        }

        var desc = op.Desc;
        var opLocal = peerConnection.SetLocalDescription(ref desc);
        yield return opLocal;

        if (opLocal.IsError)
        {
            Debug.LogError($"Set Local Description Error: {opLocal.Error.message}");
            yield break;
        }

        // Send offer to signaling server
        var offerMessage = new WebRTCMessage
        {
            type = desc.type.ToString().ToLower(),
            sdp = desc.sdp
        };

        string jsonOffer = JsonUtility.ToJson(offerMessage);
        var request = new UnityWebRequest(ServerUrl + "/offer", "POST");
        byte[] bodyRaw = Encoding.UTF8.GetBytes(jsonOffer);
        request.uploadHandler = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", "application/json");

        yield return request.SendWebRequest();

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError($"Server Error: {request.error}");
            yield break;
        }

        // Parse and set remote description
        var response = JsonUtility.FromJson<WebRTCMessage>(request.downloadHandler.text);
        var type = RTCSdpType.Answer;
        var remoteDesc = new RTCSessionDescription
        {
            type = type,
            sdp = response.sdp
        };

        var opRemote = peerConnection.SetRemoteDescription(ref remoteDesc);
        yield return opRemote;

        if (opRemote.IsError)
        {
            Debug.LogError($"Set Remote Description Error: {opRemote.Error.message}");
            yield break;
        }

        Debug.Log("WebRTC connection established successfully");
    }

    private void UpdateDisplayImage(Texture texture)
    {
        displayImage.texture = texture;
    }

    private RTCConfiguration GetDefaultConfiguration()
    {
        RTCConfiguration config = default;
        config.iceServers = new[]
        {
            new RTCIceServer { urls = new[] { "stun:stun.l.google.com:19302" } },
            new RTCIceServer 
            { 
                urls = new[] { "turn:YOUR_TURN_SERVER" },
                username = "YOUR_USERNAME",
                credential = "YOUR_PASSWORD"
            }
        };
        return config;
    }

    private void OnDestroy()
    {
        if (videoStreamTrack != null)
        {
            videoStreamTrack.OnVideoReceived -= UpdateDisplayImage;
            videoStreamTrack.Dispose();
        }

        if (peerConnection != null)
        {
            peerConnection.Close();
            peerConnection.Dispose();
        }

        if (receiveStream != null)
        {
            receiveStream.Dispose();
        }
    }

    private void OnApplicationQuit()
    {
        OnDestroy();
    }
}
