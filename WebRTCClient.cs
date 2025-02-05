using UnityEngine;
using UnityEngine.UI;
using Unity.WebRTC;
using System;
using UnityEngine.Networking;
using System.Text;
using System.Collections;
using System.Linq;

public class WebRTCClient : MonoBehaviour
{
    [SerializeField] private RawImage displayImage;
    
    private RTCPeerConnection peerConnection;
    private MediaStream videoStream;
    private const string serverUrl = "https://34.133.108.164:8443";
    
    void Start()
    {
        StartConnection();
    }

    void OnDestroy()
    {
        StopConnection();
    }

    private void StartConnection()
    {
        var configuration = new RTCConfiguration
        {
            iceServers = new[] { new RTCIceServer { urls = new[] { "stun:stun.l.google.com:19302" } } }
        };

        peerConnection = new RTCPeerConnection(ref configuration);

        // Set up event handlers
        peerConnection.OnTrack = (RTCTrackEvent e) =>
        {
            if (e.Track is MediaStreamTrack track && track.Kind == TrackKind.Video)
            {
                videoStream = e.Streams.First();
                var videoTrack = track as VideoStreamTrack;
                videoTrack.OnVideoReceived += (Texture texture) =>
                {
                    displayImage.texture = texture;
                };
            }
        };
        // Start negotiation
        StartCoroutine(Negotiate());
    }

    private IEnumerator Negotiate()
    {
        // Add transceivers (similar to client.js)
        var videoInit = new RTCRtpTransceiverInit { direction = RTCRtpTransceiverDirection.RecvOnly };
        var audioInit = new RTCRtpTransceiverInit { direction = RTCRtpTransceiverDirection.RecvOnly };
        peerConnection.AddTransceiver(TrackKind.Video, videoInit);
        peerConnection.AddTransceiver(TrackKind.Audio, audioInit);

        // Create and set local description
        var op = peerConnection.CreateOffer();
        yield return new WaitUntil(() => op.IsDone);
        
        if (op.IsError)
        {
            Debug.LogError($"Create offer failed: {op.Error.message}");
            yield break;
        }

        var desc = op.Desc;
        var setLocalDesc = peerConnection.SetLocalDescription(ref desc);
        yield return new WaitUntil(() => setLocalDesc.IsDone);

        if (setLocalDesc.IsError)
        {
            Debug.LogError($"Set local description failed: {setLocalDesc.Error.message}");
            yield break;
        }

        // Wait for ICE gathering to complete
        yield return new WaitUntil(() => peerConnection.GatheringState == RTCIceGatheringState.Complete);

        // Send offer to signaling server
        var offer = peerConnection.LocalDescription;
        var jsonOffer = JsonUtility.ToJson(new SignalingMessage
        {
            sdp = offer.sdp,
            type = offer.type.ToString().ToLower()
        });

        using (var request = new UnityWebRequest($"{serverUrl}/offer", "POST"))
        {
            byte[] bodyRaw = Encoding.UTF8.GetBytes(jsonOffer);
            request.uploadHandler = new UploadHandlerRaw(bodyRaw);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");

            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError($"Failed to send offer: {request.error}");
                yield break;
            }

            // Parse answer
            var response = JsonUtility.FromJson<SignalingMessage>(request.downloadHandler.text);
            RTCSessionDescription answer = new RTCSessionDescription
            {
                type = (RTCSdpType)Enum.Parse(typeof(RTCSdpType), response.type, true),
                sdp = response.sdp
            };

            // Set remote description
            var setRemoteDesc = peerConnection.SetRemoteDescription(ref answer);
            yield return new WaitUntil(() => setRemoteDesc.IsDone);

            if (setRemoteDesc.IsError)
            {
                Debug.LogError($"Set remote description failed: {setRemoteDesc.Error.message}");
                yield break;
            }
        }
    }

    private void StopConnection()
    {
        if (peerConnection != null)
        {
            peerConnection.Close();
            peerConnection.Dispose();
            peerConnection = null;
        }

        if (videoStream != null)
        {
            videoStream.Dispose();
            videoStream = null;
        }
    }

    [Serializable]
    private class SignalingMessage
    {
        public string sdp;
        public string type;
    }
}
