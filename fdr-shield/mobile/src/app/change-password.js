import { useState } from 'react';
import { router } from 'expo-router';
import { Text } from 'react-native';
import { Button, Card, Field, Screen } from '../components/ui';
import { useAuth } from '../providers/AuthProvider';

export default function ChangePasswordScreen(){
  const{changePassword}=useAuth();const[current,setCurrent]=useState(''),[next,setNext]=useState(''),[confirm,setConfirm]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  async function submit(){setError('');if(next!==confirm){setError('New passwords do not match.');return}setBusy(true);try{await changePassword(current,next);router.replace('/login')}catch(e){setError(e.message)}finally{setBusy(false)}}
  return <Screen title="Change password" subtitle="Choose a new password before continuing to the portal."><Card>
    <Field label="Current password" value={current} onChangeText={setCurrent} secureTextEntry autoCapitalize="none"/>
    <Field label="New password" value={next} onChangeText={setNext} secureTextEntry autoCapitalize="none"/>
    <Field label="Confirm new password" value={confirm} onChangeText={setConfirm} secureTextEntry autoCapitalize="none"/>
    {error?<Text accessibilityRole="alert" style={{color:'#B42318'}}>{error}</Text>:null}
    <Button title={busy?'Saving…':'Save password'} onPress={submit} disabled={busy||!current||next.length<12||!confirm}/>
  </Card></Screen>;
}
